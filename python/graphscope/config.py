#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright 2020 Alibaba Group Holding Limited. All Rights Reserved.
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

""" GraphScope default configuration.
"""

from graphscope.version import __version__


class GSConfig(object):
    # the endpoint of a pre-launched GraphScope instance.
    addr = None

    # "k8s" or "hosts"
    cluster_type = "k8s"

    k8s_namespace = None

    # image
    k8s_zookeeper_image = "zookeeper:3.4.14"
    k8s_etcd_image = "quay.io/coreos/etcd:v3.4.13"
    k8s_gs_image = "registry.cn-hongkong.aliyuncs.com/graphscope/graphscope:{0}".format(
        __version__
    )
    k8s_gie_graph_manager_image = "registry.cn-hongkong.aliyuncs.com/graphscope/maxgraph_standalone_manager:{0}".format(
        __version__
    )

    # image pull configuration
    k8s_image_pull_policy = "IfNotPresent"
    k8s_image_pull_secrets = []

    # coordinator resource configuration
    k8s_coordinator_cpu = 1.0
    k8s_coordinator_mem = "4Gi"

    # etcd resource configuration
    k8s_etcd_num_pods = 3
    k8s_etcd_cpu = 0.5
    k8s_etcd_mem = "128Mi"

    # zookeeper resource configuration
    k8s_zookeeper_cpu = 0.5
    k8s_zookeeper_mem = "256Mi"

    # GIE graph manager resource configuration
    k8s_gie_graph_manager_cpu = 1.0
    k8s_gie_graph_manager_mem = "4Gi"

    # GIE gremlin server resource configuration
    k8s_gie_gremlin_server_cpu = 1.0
    k8s_gie_gremlin_server_mem = "1Gi"

    # vineyard resource configuration
    k8s_vineyard_daemonset = "none"
    k8s_vineyard_cpu = 0.5
    k8s_vineyard_mem = "512Mi"
    vineyard_shared_mem = "4Gi"

    # engine resource configuration
    k8s_engine_cpu = 0.5
    k8s_engine_mem = "4Gi"

    # mars resource configuration
    mars_worker_cpu = 0.5
    mars_worker_mem = "4Gi"
    mars_scheduler_cpu = 0.5
    mars_scheduler_mem = "2Gi"

    # launch graphscope with mars
    with_mars = False

    k8s_volumes = {}

    k8s_service_type = "NodePort"

    # support resource preemption or resource guarantee
    preemptive = True

    k8s_waiting_for_delete = False
    num_workers = 2
    show_log = False
    log_level = "INFO"

    # GIE engine params
    engine_params = None

    # GIE instance will be created automatically when a property graph loaded.
    # Otherwise, you should create a GIE instance manually by `sess.gremlin` if
    # `initializing_interactive_engine` is False
    initializing_interactive_engine = True

    timeout_seconds = 600

    # kill GraphScope instance after seconds of client disconnect
    # disable dangling check by setting -1.
    dangling_timeout_seconds = 600
