#! /usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright 2020 Alibaba Group Holding Limited.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Coordinator between client and engines"""

import argparse
import atexit
import hashlib
import json
import logging
import os
import queue
import random
import signal
import string
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent import futures
from io import StringIO

import grpc

from gscoordinator.io_utils import StdoutWrapper

# capture system stdout
sys.stdout = StdoutWrapper(sys.stdout)

from graphscope.proto import attr_value_pb2
from graphscope.proto import coordinator_service_pb2_grpc
from graphscope.proto import engine_service_pb2_grpc
from graphscope.proto import error_codes_pb2
from graphscope.proto import message_pb2
from graphscope.proto import op_def_pb2
from graphscope.proto import types_pb2

from gscoordinator.cluster import KubernetesClusterLauncher
from gscoordinator.launcher import LocalLauncher
from gscoordinator.object_manager import GraphMeta
from gscoordinator.object_manager import LibMeta
from gscoordinator.object_manager import ObjectManager
from gscoordinator.utils import compile_app
from gscoordinator.utils import compile_graph_frame
from gscoordinator.utils import create_single_op_dag
from gscoordinator.utils import dump_string
from gscoordinator.utils import get_app_sha256
from gscoordinator.utils import get_graph_sha256
from gscoordinator.utils import get_lib_path
from gscoordinator.utils import str2bool
from gscoordinator.utils import to_maxgraph_schema
from gscoordinator.version import __version__

COORDINATOR_HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPHSCOPE_HOME = os.path.join(COORDINATOR_HOME, "..")

WORKSPACE = "/tmp/gs"
DEFAULT_GS_CONFIG_FILE = ".gs_conf.yaml"
ANALYTICAL_ENGINE_HOME = os.path.join(GRAPHSCOPE_HOME, "analytical_engine")
ANALYTICAL_ENGINE_PATH = os.path.join(ANALYTICAL_ENGINE_HOME, "build", "grape_engine")
TEMPLATE_DIR = os.path.join(COORDINATOR_HOME, "gscoordinator", "template")
BUILTIN_APP_RESOURCE_PATH = os.path.join(
    COORDINATOR_HOME, "gscoordinator", "builtin/app/builtin_app.gar"
)
GS_DEBUG_ENDPOINT = os.environ.get("GS_DEBUG_ENDPOINT", "")

ENGINE_CONTAINER = "engine"
VINEYARD_CONTAINER = "vineyard"

logger = logging.getLogger("graphscope")


class CoordinatorServiceServicer(
    coordinator_service_pb2_grpc.CoordinatorServiceServicer
):
    """Provides methods that implement functionality of master service server.
    Holding:
        1. process: the grape-engine process.
        2. session_id: the handle for a particular session to engine
        3. vineyard_ipc_socket: returned by grape-engine
        4. vineyard_rpc_socket: returned by grape-engine
        5. engine_endpoint: the endpoint of grape-engine
        6. engine_servicer: grpc connection to grape-engine

    """

    def __init__(self, launcher, dangling_timeout_seconds, log_level="INFO"):
        self._launcher = launcher

        self._request = None
        self._object_manager = ObjectManager()
        self._dangling_detecting_timer = None
        self._config_logging(log_level)

        # only one connection is allowed at the same time
        # generate session id  when a client connection is established
        self._session_id = None

        # launch engines
        if len(GS_DEBUG_ENDPOINT) > 0:
            logger.info(
                "Coordinator will connect to engine with endpoint: " + GS_DEBUG_ENDPOINT
            )
            self._launcher._analytical_engine_endpoint = GS_DEBUG_ENDPOINT
        else:
            if not self._launcher.start():
                raise RuntimeError("Coordinator Launching failed.")

        self._launcher_type = self._launcher.type()
        if self._launcher_type == types_pb2.K8S:
            self._pods_list = self._launcher.get_pods_list()
            self._k8s_namespace = self._launcher.get_namespace()
        else:
            self._pods_list = []  # locally launched
            self._k8s_namespace = ""

        # analytical engine
        self._analytical_engine_stub = self._create_grpc_stub()
        self._analytical_engine_config = None
        self._analytical_engine_endpoint = None

        self._builtin_workspace = os.path.join(WORKSPACE, "builtin")
        # udf app workspace should be bound to a specific session when client connect.
        self._udf_app_workspace = None

        # control log fetching
        self._streaming_logs = True

        # dangling check
        self._dangling_timeout_seconds = dangling_timeout_seconds
        if self._dangling_timeout_seconds >= 0:
            self._dangling_detecting_timer = threading.Timer(
                interval=self._dangling_timeout_seconds,
                function=self._cleanup,
                args=(
                    True,
                    True,
                ),
            )
            self._dangling_detecting_timer.start()

        atexit.register(self._cleanup)

    def __del__(self):
        self._cleanup()

    def _generate_session_id(self):
        return "session_" + "".join(
            [random.choice(string.ascii_lowercase) for _ in range(8)]
        )

    def _config_logging(self, log_level):
        """Set log level basic on config.
        Args:
            log_level (str): Log level of stdout handler
        """
        if log_level:
            log_level = log_level.upper()
        logger = logging.getLogger("graphscope")
        logger.setLevel(logging.DEBUG)

        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(log_level)

        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s][%(module)s:%(lineno)d]: %(message)s"
        )
        stdout_handler.setFormatter(formatter)

        logger.addHandler(stdout_handler)

    def ConnectSession(self, request, context):
        # A session is already connected.
        if self._request:
            return self._make_response(
                message_pb2.ConnectSessionResponse,
                code=error_codes_pb2.CONNECTION_ERROR,
                error_msg="Cannot setup more than one connection at the same time.",
            )

        # Connect to serving coordinator.
        self._request = request
        self._analytical_engine_config = self._get_engine_config()

        # Generate session id
        self._session_id = self._generate_session_id()
        self._udf_app_workspace = os.path.join(WORKSPACE, self._session_id)

        # Session connected, fetch logs via gRPC.
        self._streaming_logs = True
        sys.stdout.drop(False)

        return self._make_response(
            message_pb2.ConnectSessionResponse,
            code=error_codes_pb2.OK,
            session_id=self._session_id,
            cluster_type=self._launcher.type(),
            num_workers=self._launcher.num_workers,
            engine_config=json.dumps(self._analytical_engine_config),
            pod_name_list=self._pods_list,
            namespace=self._k8s_namespace,
        )

    def HeartBeat(self, request, context):
        if self._request and self._request.dangling_timeout_seconds >= 0:
            # Reset dangling detect timer
            if self._dangling_detecting_timer:
                self._dangling_detecting_timer.cancel()

            self._dangling_detecting_timer = threading.Timer(
                interval=self._request.dangling_timeout_seconds,
                function=self._cleanup,
                args=(
                    self._request.cleanup_instance,
                    True,
                ),
            )
            self._dangling_detecting_timer.start()

        # analytical engine
        request = message_pb2.HeartBeatRequest()
        try:
            self._analytical_engine_stub.HeartBeat(request)
        except Exception as e:
            return self._make_response(
                message_pb2.HeartBeatResponse,
                error_codes_pb2.CONNECTION_ERROR,
                "connect analytical engine failed: {}".format(str(e)),
            )
        else:
            return self._make_response(
                message_pb2.HeartBeatResponse, error_codes_pb2.OK
            )

    def RunStep(self, request, context):  # noqa: C901
        # only one op in one step is allowed.
        if len(request.dag_def.op) != 1:
            return self._make_response(
                message_pb2.RunStepResponse,
                error_codes_pb2.INVALID_ARGUMENT_ERROR,
                "Request's op size is not equal to 1.",
            )

        op = request.dag_def.op[0]

        # Compile app or not.
        if op.op == types_pb2.CREATE_APP:
            try:
                op, app_sig, app_lib_path = self._maybe_compile_app(op)
            except Exception as e:
                error_msg = "Failed to compile app: {}".format(str(e))
                logger.error(error_msg)
                return self._make_response(
                    message_pb2.RunStepResponse,
                    error_codes_pb2.COMPILATION_ERROR,
                    error_msg,
                    op,
                )

        # If engine crashed, we will get a SocketClosed grpc Exception.
        # In that case, we should notify client the engine is dead.

        # Compile graph or not
        # arrow property graph and project graph need to compile
        if (
            (
                op.op == types_pb2.CREATE_GRAPH
                and op.attr[types_pb2.GRAPH_TYPE].graph_type == types_pb2.ARROW_PROPERTY
            )
            or op.op == types_pb2.TRANSFORM_GRAPH
            or op.op == types_pb2.PROJECT_TO_SIMPLE
            or op.op == types_pb2.ADD_LABELS
        ):
            try:
                op = self._maybe_register_graph(op, request.session_id)
            except grpc.RpcError as e:
                logger.error("self._launcher.poll() = %s", self._launcher.poll())
                if self._launcher.poll() is not None:
                    message = "Analytical engine exited with %s" % self._launcher.poll()
                else:
                    message = str(e)
                return self._make_response(
                    message_pb2.RunStepResponse,
                    error_codes_pb2.FATAL_ERROR,
                    message,
                    op,
                )
            except Exception as e:
                error_msg = "Graph compile error: {}".format(str(e))
                logger.error(error_msg)
                return self._make_response(
                    message_pb2.RunStepResponse,
                    error_codes_pb2.COMPILATION_ERROR,
                    error_msg,
                    op,
                )

        try:
            response = self._analytical_engine_stub.RunStep(request)
        except grpc.RpcError as e:
            logger.error("self._launcher.poll() = %s", self._launcher.poll())
            if self._launcher.poll() is not None:
                message = "Analytical engine exited with %s" % self._launcher.poll()
            else:
                message = str(e)
            return self._make_response(
                message_pb2.RunStepResponse, error_codes_pb2.FATAL_ERROR, message, op
            )
        except Exception as e:
            return self._make_response(
                message_pb2.RunStepResponse, error_codes_pb2.UNKNOWN, str(e), op
            )

        if response.status.code == error_codes_pb2.OK:
            if op.op in (
                types_pb2.CREATE_GRAPH,
                types_pb2.PROJECT_GRAPH,
                types_pb2.ADD_LABELS,
                types_pb2.ADD_COLUMN,
            ):
                schema_path = os.path.join("/tmp", response.graph_def.key + ".json")
                self._object_manager.put(
                    response.graph_def.key,
                    GraphMeta(
                        response.graph_def.key,
                        response.graph_def.vineyard_id,
                        response.graph_def.schema_def,
                        schema_path,
                    ),
                )
                if response.graph_def.graph_type == types_pb2.ARROW_PROPERTY:
                    dump_string(
                        to_maxgraph_schema(
                            response.graph_def.schema_def.property_schema_json
                        ),
                        schema_path,
                    )
                    response.graph_def.schema_path = schema_path
            elif op.op == types_pb2.CREATE_APP:
                self._object_manager.put(
                    app_sig,
                    LibMeta(response.result.decode("utf-8"), "app", app_lib_path),
                )
            elif op.op == types_pb2.UNLOAD_GRAPH:
                self._object_manager.pop(op.attr[types_pb2.GRAPH_NAME].s.decode())
            elif op.op == types_pb2.UNLOAD_APP:
                self._object_manager.pop(op.attr[types_pb2.APP_NAME].s.decode())

        return response

    def _maybe_compile_app(self, op):
        app_sig = get_app_sha256(op.attr)
        space = self._builtin_workspace
        if types_pb2.GAR in op.attr:
            space = self._udf_app_workspace
        app_lib_path = get_lib_path(os.path.join(space, app_sig), app_sig)
        if not os.path.isfile(app_lib_path):
            compiled_path = self._compile_lib_and_distribute(compile_app, app_sig, op)
            if app_lib_path != compiled_path:
                raise RuntimeError("Computed path not equal to compiled path.")

        op.attr[types_pb2.APP_LIBRARY_PATH].CopyFrom(
            attr_value_pb2.AttrValue(s=app_lib_path.encode("utf-8"))
        )
        return op, app_sig, app_lib_path

    def _maybe_register_graph(self, op, session_id):
        graph_sig = get_graph_sha256(op.attr)
        space = self._builtin_workspace
        graph_lib_path = get_lib_path(os.path.join(space, graph_sig), graph_sig)
        if not os.path.isfile(graph_lib_path):
            compiled_path = self._compile_lib_and_distribute(
                compile_graph_frame, graph_sig, op
            )
            if graph_lib_path != compiled_path:
                raise RuntimeError("Computed path not equal to compiled path.")
        if graph_sig not in self._object_manager:
            # register graph
            op_def = op_def_pb2.OpDef(op=types_pb2.REGISTER_GRAPH_TYPE)
            op_def.attr[types_pb2.GRAPH_LIBRARY_PATH].CopyFrom(
                attr_value_pb2.AttrValue(s=graph_lib_path.encode("utf-8"))
            )
            op_def.attr[types_pb2.TYPE_SIGNATURE].CopyFrom(
                attr_value_pb2.AttrValue(s=graph_sig.encode("utf-8"))
            )
            op_def.attr[types_pb2.GRAPH_TYPE].CopyFrom(
                attr_value_pb2.AttrValue(
                    graph_type=op.attr[types_pb2.GRAPH_TYPE].graph_type
                )
            )
            dag_def = op_def_pb2.DagDef()
            dag_def.op.extend([op_def])
            register_request = message_pb2.RunStepRequest(
                session_id=session_id, dag_def=dag_def
            )
            register_response = self._analytical_engine_stub.RunStep(register_request)

            if register_response.status.code == error_codes_pb2.OK:
                self._object_manager.put(
                    graph_sig,
                    LibMeta(register_response.result, "graph_frame", graph_lib_path),
                )
            else:
                raise RuntimeError("Error occur when register graph")
        op.attr[types_pb2.TYPE_SIGNATURE].CopyFrom(
            attr_value_pb2.AttrValue(s=graph_sig.encode("utf-8"))
        )
        return op

    def FetchLogs(self, request, context):
        while self._streaming_logs:
            try:
                message = sys.stdout.poll(timeout=3)
            except queue.Empty:
                pass
            else:
                if self._streaming_logs:
                    yield self._make_response(
                        message_pb2.FetchLogsResponse,
                        error_codes_pb2.OK,
                        message=message,
                    )

    def CloseSession(self, request, context):
        """
        Disconnect session, note that it doesn't clean up any resources.
        """
        if request.session_id != self._session_id:
            return self._make_response(
                message_pb2.CloseSessionResponse,
                error_codes_pb2.INVALID_ARGUMENT_ERROR,
                "Session handle does not match",
            )

        self._cleanup(
            cleanup_instance=self._request.cleanup_instance, is_dangling=False
        )
        self._request = None

        # Session closed, stop streaming logs
        sys.stdout.drop(True)
        self._streaming_logs = False

        return self._make_response(message_pb2.CloseSessionResponse, error_codes_pb2.OK)

    def CreateInteractiveInstance(self, request, context):
        object_id = request.object_id
        gremlin_server_cpu = request.gremlin_server_cpu
        gremlin_server_mem = request.gremlin_server_mem

        with open(request.schema_path) as file:
            schema_json = file.read()

        params = {
            "graphName": "%s" % object_id,
        }

        if self._launcher_type == types_pb2.K8S:
            post_url = "{0}/instance/create".format(self._launcher.get_manager_host())
            params.update(
                {
                    "schemaJson": schema_json,
                    "podNameList": ",".join(self._pods_list),
                    "containerName": ENGINE_CONTAINER,
                    "preemptive": str(self._launcher.preemptive),
                    "gremlinServerCpu": str(gremlin_server_cpu),
                    "gremlinServerMem": gremlin_server_mem,
                }
            )
            engine_params = [
                "{}:{}".format(key, value)
                for key, value in request.engine_params.items()
            ]
            params["engineParams"] = "'{}'".format(";".join(engine_params))
        else:
            manager_host = self._launcher.graph_manager_endpoint
            params.update(
                {
                    "vineyardIpcSocket": self._launcher.vineyard_socket,
                    "schemaPath": request.schema_path,
                    "zookeeperPort": str(self._launcher.zookeeper_port),
                }
            )
            post_url = "http://%s/instance/create_local" % manager_host

        post_data = urllib.parse.urlencode(params).encode("utf-8")
        create_res = urllib.request.urlopen(url=post_url, data=post_data)
        res_json = json.load(create_res)
        error_code = res_json["errorCode"]
        if error_code == 0:
            front_host = res_json["frontHost"]
            front_port = res_json["frontPort"]
            logger.info(
                "build frontend %s:%d for graph %ld",
                front_host,
                front_port,
                object_id,
            )
            return message_pb2.CreateInteractiveResponse(
                status=message_pb2.ResponseStatus(code=error_codes_pb2.OK),
                frontend_host=front_host,
                frontend_port=front_port,
                object_id=object_id,
            )
        else:
            error_message = (
                "create interactive instance for object id %ld failed with error code %d message %s"
                % (object_id, error_code, res_json["errorMessage"])
            )
            logger.error(error_message)
            return message_pb2.CreateInteractiveResponse(
                status=message_pb2.ResponseStatus(
                    code=error_codes_pb2.INTERACTIVE_ENGINE_INTERNAL_ERROR,
                    error_msg=error_message,
                ),
                frontend_host="",
                frontend_port=0,
                object_id=object_id,
            )

    def CloseInteractiveInstance(self, request, context):
        object_id = request.object_id
        if self._launcher_type == types_pb2.K8S:
            manager_host = self._launcher.get_manager_host()
            pod_name_list = ",".join(self._pods_list)
            close_url = "%s/instance/close?graphName=%ld&podNameList=%s&containerName=%s&waitingForDelete=%s" % (
                manager_host,
                object_id,
                pod_name_list,
                ENGINE_CONTAINER,
                str(self._launcher.waiting_for_delete()),
            )
        else:
            manager_host = self._launcher.graph_manager_endpoint
            close_url = "http://%s/instance/close_local?graphName=%ld" % (
                manager_host,
                object_id,
            )
        logger.info("Coordinator close interactive instance with url[%s]" % close_url)
        try:
            close_res = urllib.request.urlopen(close_url).read()
        except Exception as e:
            logger.error("Failed to close interactive instance: %s", e)
            return message_pb2.CloseInteractiveResponse(
                status=message_pb2.ResponseStatus(
                    code=error_codes_pb2.INTERACTIVE_ENGINE_INTERNAL_ERROR,
                    error_msg="Internal error during close interactive instance: %d, %s"
                    % (400, e),
                )
            )
        res_json = json.loads(close_res.decode("utf-8", errors="ignore"))
        error_code = res_json["errorCode"]
        if 0 == error_code:
            return message_pb2.CloseInteractiveResponse(
                status=message_pb2.ResponseStatus(code=error_codes_pb2.OK)
            )
        else:
            error_message = (
                "Failed to close interactive instance for object id %ld with error code %d message %s"
                % (object_id, error_code, res_json["errorMessage"])
            )
            logger.error("Failed to close interactive instance: %s", error_message)
            return message_pb2.CloseInteractiveResponse(
                status=message_pb2.ResponseStatus(
                    code=error_codes_pb2.INTERACTIVE_ENGINE_INTERNAL_ERROR,
                    error_msg=error_message,
                )
            )

    def CreateLearningInstance(self, request, context):
        logger.info(
            "Coordinator create learning instance with object id %ld",
            request.object_id,
        )
        object_id = request.object_id
        handle = request.handle
        config = request.config
        endpoints = self._launcher.create_learning_instance(object_id, handle, config)
        return message_pb2.CreateLearningInstanceResponse(
            status=message_pb2.ResponseStatus(code=error_codes_pb2.OK),
            endpoints=",".join(endpoints),
        )

    def CloseLearningInstance(self, request, context):
        logger.info(
            "Coordinator close learning instance with object id %ld",
            request.object_id,
        )
        self._launcher.close_learning_instance(request.object_id)
        return message_pb2.CloseLearningInstanceResponse(
            status=message_pb2.ResponseStatus(code=error_codes_pb2.OK)
        )

    @staticmethod
    def _make_response(resp_cls, code, error_msg="", op=None, **args):
        resp = resp_cls(
            status=message_pb2.ResponseStatus(code=code, error_msg=error_msg), **args
        )
        if op:
            resp.status.op.CopyFrom(op)
        return resp

    def _cleanup(self, cleanup_instance=True, is_dangling=False):
        # clean up session resources.
        for key in self._object_manager.keys():
            obj = self._object_manager.get(key)
            obj_type = obj.type
            unload_type = None

            if obj_type == "app":
                unload_type = types_pb2.UNLOAD_APP
                config = {
                    types_pb2.APP_NAME: attr_value_pb2.AttrValue(
                        s=obj.key.encode("utf-8")
                    )
                }
            elif obj_type == "graph":
                unload_type = types_pb2.UNLOAD_GRAPH
                config = {
                    types_pb2.GRAPH_NAME: attr_value_pb2.AttrValue(
                        s=obj.key.encode("utf-8")
                    )
                }
                # dynamic graph doesn't have a vineyard id
                if obj.vineyard_id != -1:
                    config[types_pb2.VINEYARD_ID] = attr_value_pb2.AttrValue(
                        i=obj.vineyard_id
                    )

            if unload_type:
                dag_def = create_single_op_dag(unload_type, config)
                request = message_pb2.RunStepRequest(
                    session_id=self._session_id, dag_def=dag_def
                )
                self._analytical_engine_stub.RunStep(request)

        self._object_manager.clear()

        self._request = None

        # cancel dangling detect timer
        if self._dangling_detecting_timer:
            self._dangling_detecting_timer.cancel()

        # close engines
        if cleanup_instance:
            self._analytical_engine_stub = None
            self._analytical_engine_endpoint = None
            self._launcher.stop(is_dangling=is_dangling)

        self._session_id = None

    def _create_grpc_stub(self):
        options = [
            ("grpc.max_send_message_length", 2147483647),
            ("grpc.max_receive_message_length", 2147483647),
        ]

        channel = grpc.insecure_channel(
            self._launcher.analytical_engine_endpoint, options=options
        )
        return engine_service_pb2_grpc.EngineServiceStub(channel)

    def _get_engine_config(self):
        op_def = op_def_pb2.OpDef(op=types_pb2.GET_ENGINE_CONFIG)
        dag_def = op_def_pb2.DagDef()
        dag_def.op.extend([op_def])
        fetch_request = message_pb2.RunStepRequest(
            session_id=self._session_id, dag_def=dag_def
        )
        fetch_response = self._analytical_engine_stub.RunStep(fetch_request)
        config = json.loads(fetch_response.result.decode("utf-8"))
        if self._launcher_type == types_pb2.K8S:
            config["vineyard_service_name"] = self._launcher.get_vineyard_service_name()
            config["vineyard_rpc_endpoint"] = self._launcher.get_vineyard_rpc_endpoint()
            config["mars_endpoint"] = self._launcher.get_mars_scheduler_endpoint()
        else:
            config["engine_hosts"] = self._launcher.hosts
            config["mars_endpoint"] = None
        return config

    def _compile_lib_and_distribute(self, compile_func, lib_name, op):
        if self._analytical_engine_config is None:
            # fetch NETWORKX compile option from engine
            self._analytical_engine_config = self._get_engine_config()
        space = self._builtin_workspace
        if types_pb2.GAR in op.attr:
            space = self._udf_app_workspace
        app_lib_path = compile_func(
            space, lib_name, op.attr, self._analytical_engine_config
        )
        self._launcher.distribute_file(app_lib_path)
        return app_lib_path


def parse_sys_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument(
        "--num_workers",
        type=int,
        default=4,
        help="The number of engine workers.",
    )
    parser.add_argument(
        "--preemptive",
        type=str2bool,
        nargs="?",
        const=True,
        default=True,
        help="Support resource preemption or resource guarantee",
    )
    parser.add_argument(
        "--instance_id",
        type=str,
        help="Unique id for each GraphScope instance.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=63800,
        help="Coordinator service port.",
    )
    parser.add_argument(
        "--log_level",
        type=str,
        default="info",
        help="Log level, info or debug.",
    )
    parser.add_argument(
        "--hosts",
        type=str,
        default="localhost",
        help="A list of hostname, comma separated.",
    )
    parser.add_argument(
        "--vineyard_socket",
        type=str,
        default=None,
        help="Socket path to connect to vineyard, random socket will be created if param missing.",
    )
    parser.add_argument(
        "--cluster_type",
        type=str,
        default="k8s",
        help="Deploy graphscope components on local or kubernetes cluster.",
    )
    parser.add_argument(
        "--k8s_namespace",
        type=str,
        default="graphscope",
        help="Contains the namespace to create all resource inside, namespace must be exist.",
    )
    parser.add_argument(
        "--k8s_service_type",
        type=str,
        default="NodePort",
        help="Valid options are NodePort, and LoadBalancer.",
    )
    parser.add_argument(
        "--k8s_gs_image",
        type=str,
        default="registry.cn-hongkong.aliyuncs.com/graphscope/graphscope:{}".format(
            __version__
        ),
        help="Docker image of graphscope engines.",
    )
    parser.add_argument(
        "--k8s_coordinator_name",
        type=str,
        default="",
        help="Coordinator name in graphscope instance.",
    )
    parser.add_argument(
        "--k8s_coordinator_service_name",
        type=str,
        default="",
        help="Coordinator service name in graphscope instance.",
    )
    parser.add_argument(
        "--k8s_etcd_image",
        type=str,
        default="registry.cn-hongkong.aliyuncs.com/graphscope/etcd:v3.4.13",
        help="Docker image of etcd, used by vineyard.",
    )
    parser.add_argument(
        "--k8s_gie_graph_manager_image",
        type=str,
        default="registry.cn-hongkong.aliyuncs.com/graphscope/maxgraph_standalone_manager:{}".format(
            __version__
        ),
        help="Graph Manager image of graph interactive engine.",
    )
    parser.add_argument(
        "--k8s_zookeeper_image",
        type=str,
        default="registry.cn-hongkong.aliyuncs.com/graphscope/zookeeper:3.4.10",
        help="Docker image of zookeeper, used by graph interactive engine.",
    )
    parser.add_argument(
        "--k8s_image_pull_policy",
        type=str,
        default="IfNotPresent",
        help="Kubernetes image pull policy.",
    )
    parser.add_argument(
        "--k8s_image_pull_secrets",
        type=str,
        default="graphscope",
        help="A list of secret name, comma separated.",
    )
    parser.add_argument(
        "--k8s_vineyard_daemonset",
        type=str,
        default="",
        help="Try to use the existing vineyard DaemonSet with name 'k8s_vineyard_daemonset'.",
    )
    parser.add_argument(
        "--k8s_vineyard_cpu",
        type=float,
        default=1.0,
        help="Cpu cores of vinayard container.",
    )
    parser.add_argument(
        "--k8s_vineyard_mem",
        type=str,
        default="256Mi",
        help="Memory of vineyard container, suffix with ['Mi', 'Gi', 'Ti'].",
    )
    parser.add_argument(
        "--vineyard_shared_mem",
        type=str,
        default="8Gi",
        help="Plasma memory in vineyard, suffix with ['Mi', 'Gi', 'Ti'].",
    )
    parser.add_argument(
        "--k8s_engine_cpu",
        type=float,
        default=1.0,
        help="Cpu cores of engine container, default: 1.0",
    )
    parser.add_argument(
        "--k8s_engine_mem",
        type=str,
        default="256Mi",
        help="Memory of engine container, suffix with ['Mi', 'Gi', 'Ti'].",
    )
    parser.add_argument(
        "--k8s_etcd_num_pods",
        type=int,
        default=3,
        help="The number of etcd pods.",
    )
    parser.add_argument(
        "--k8s_etcd_cpu",
        type=float,
        default=1.0,
        help="Cpu cores of etcd pod, default: 1.0",
    )
    parser.add_argument(
        "--k8s_etcd_mem",
        type=str,
        default="256Mi",
        help="Memory of etcd pod, suffix with ['Mi', 'Gi', 'Ti'].",
    )
    parser.add_argument(
        "--k8s_zookeeper_cpu",
        type=float,
        default=1.0,
        help="Cpu cores of zookeeper container, default: 1.0",
    )
    parser.add_argument(
        "--k8s_zookeeper_mem",
        type=str,
        default="256Mi",
        help="Memory of zookeeper container, suffix with ['Mi', 'Gi', 'Ti'].",
    )
    parser.add_argument(
        "--k8s_gie_graph_manager_cpu",
        type=float,
        default=1.0,
        help="Cpu cores of graph manager container, default: 1.0",
    )
    parser.add_argument(
        "--k8s_gie_graph_manager_mem",
        type=str,
        default="256Mi",
        help="Memory of graph manager container, suffix with ['Mi', 'Gi', 'Ti'].",
    )
    parser.add_argument(
        "--k8s_with_mars",
        type=str2bool,
        nargs="?",
        const=True,
        default=False,
        help="Enable mars or not.",
    )
    parser.add_argument(
        "--k8s_mars_worker_cpu",
        type=float,
        default=0.5,
        help="Cpu cores of mars worker container, default: 0.5",
    )
    parser.add_argument(
        "--k8s_mars_worker_mem",
        type=str,
        default="4Gi",
        help="Memory of mars worker container, default: 4Gi",
    )
    parser.add_argument(
        "--k8s_mars_scheduler_cpu",
        type=float,
        default=0.5,
        help="Cpu cores of mars scheduler container, default: 0.5",
    )
    parser.add_argument(
        "--k8s_mars_scheduler_mem",
        type=str,
        default="2Gi",
        help="Memory of mars scheduler container, default: 2Gi",
    )
    parser.add_argument(
        "--k8s_volumes",
        type=str,
        default="{}",
        help="A json string for kubernetes volumes.",
    )
    parser.add_argument(
        "--timeout_seconds",
        type=int,
        default=600,
        help="Launch failed after waiting timeout seconds.",
    )
    parser.add_argument(
        "--dangling_timeout_seconds",
        type=int,
        default=600,
        help="Kill graphscope instance after seconds of client disconnect.",
    )
    parser.add_argument(
        "--waiting_for_delete",
        type=str2bool,
        nargs="?",
        const=True,
        default=False,
        help="Waiting for delete graphscope instance.",
    )
    parser.add_argument(
        "--k8s_delete_namespace",
        type=str2bool,
        nargs="?",
        const=True,
        default=False,
        help="Delete namespace or not.",
    )
    return parser.parse_args()


def launch_graphscope():
    args = parse_sys_args()
    logger.info("Launching with args %s", args)

    if args.cluster_type == "k8s":
        launcher = KubernetesClusterLauncher(
            namespace=args.k8s_namespace,
            service_type=args.k8s_service_type,
            gs_image=args.k8s_gs_image,
            etcd_image=args.k8s_etcd_image,
            zookeeper_image=args.k8s_zookeeper_image,
            gie_graph_manager_image=args.k8s_gie_graph_manager_image,
            coordinator_name=args.k8s_coordinator_name,
            coordinator_service_name=args.k8s_coordinator_service_name,
            etcd_num_pods=args.k8s_etcd_num_pods,
            etcd_cpu=args.k8s_etcd_cpu,
            etcd_mem=args.k8s_etcd_mem,
            zookeeper_cpu=args.k8s_zookeeper_cpu,
            zookeeper_mem=args.k8s_zookeeper_mem,
            gie_graph_manager_cpu=args.k8s_gie_graph_manager_cpu,
            gie_graph_manager_mem=args.k8s_gie_graph_manager_mem,
            engine_cpu=args.k8s_engine_cpu,
            engine_mem=args.k8s_engine_mem,
            vineyard_daemonset=args.k8s_vineyard_daemonset,
            vineyard_cpu=args.k8s_vineyard_cpu,
            vineyard_mem=args.k8s_vineyard_mem,
            vineyard_shared_mem=args.vineyard_shared_mem,
            mars_worker_cpu=args.k8s_mars_worker_cpu,
            mars_worker_mem=args.k8s_mars_worker_mem,
            mars_scheduler_cpu=args.k8s_mars_scheduler_cpu,
            mars_scheduler_mem=args.k8s_mars_scheduler_mem,
            with_mars=args.k8s_with_mars,
            image_pull_policy=args.k8s_image_pull_policy,
            image_pull_secrets=args.k8s_image_pull_secrets,
            volumes=args.k8s_volumes,
            num_workers=args.num_workers,
            preemptive=args.preemptive,
            instance_id=args.instance_id,
            log_level=args.log_level,
            timeout_seconds=args.timeout_seconds,
            waiting_for_delete=args.waiting_for_delete,
            delete_namespace=args.k8s_delete_namespace,
        )
    elif args.cluster_type == "hosts":
        launcher = LocalLauncher(
            num_workers=args.num_workers,
            hosts=args.hosts,
            vineyard_socket=args.vineyard_socket,
            shared_mem=args.vineyard_shared_mem,
            log_level=args.log_level,
            instance_id=args.instance_id,
            timeout_seconds=args.timeout_seconds,
        )
    else:
        raise RuntimeError("Expect hosts or k8s of cluster_type parameter")

    coordinator_service_servicer = CoordinatorServiceServicer(
        launcher=launcher,
        dangling_timeout_seconds=args.dangling_timeout_seconds,
        log_level=args.log_level,
    )

    # register gRPC server
    server = grpc.server(futures.ThreadPoolExecutor(os.cpu_count() or 1))
    coordinator_service_pb2_grpc.add_CoordinatorServiceServicer_to_server(
        coordinator_service_servicer, server
    )
    server.add_insecure_port("0.0.0.0:{}".format(args.port))
    logger.info("Coordinator server listen at 0.0.0.0:%d", args.port)

    server.start()

    # handle SIGTERM signal
    def terminate(signum, frame):
        global coordinator_service_servicer
        coordinator_service_servicer._cleanup()

    signal.signal(signal.SIGTERM, terminate)

    try:
        # Grpc has handled SIGINT
        server.wait_for_termination()
    except KeyboardInterrupt:
        coordinator_service_servicer._cleanup()


if __name__ == "__main__":
    launch_graphscope()
