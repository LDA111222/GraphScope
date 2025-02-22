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

import logging
import os
import random
import string
import subprocess
import sys

import numpy as np
import pytest

import graphscope
from graphscope.config import GSConfig as gs_config
from graphscope.dataset.ldbc import load_ldbc
from graphscope.dataset.modern_graph import load_modern_graph
from graphscope.framework.graph import Graph
from graphscope.framework.loader import Loader

graphscope.set_option(show_log=True)
logger = logging.getLogger("graphscope")


def get_k8s_volumes():
    k8s_volumes = {
        "data": {
            "type": "hostPath",
            "field": {"path": os.environ["GS_TEST_DIR"], "type": "Directory"},
            "mounts": {"mountPath": "/testingdata"},
        }
    }
    return k8s_volumes


def get_gs_image_on_ci_env():
    if "GS_IMAGE" in os.environ and "GIE_MANAGER_IMAGE" in os.environ:
        return os.environ["GS_IMAGE"], os.environ["GIE_MANAGER_IMAGE"]
    else:
        return gs_config.k8s_gs_image, gs_config.k8s_gie_graph_manager_image


@pytest.fixture
def gs_session():
    gs_image, gie_manager_image = get_gs_image_on_ci_env()
    sess = graphscope.session(
        num_workers=1,
        k8s_gs_image=gs_image,
        k8s_gie_graph_manager_image=gie_manager_image,
        k8s_coordinator_cpu=2,
        k8s_coordinator_mem="4Gi",
        k8s_vineyard_cpu=2,
        k8s_vineyard_mem="512Mi",
        k8s_engine_cpu=2,
        k8s_engine_mem="4Gi",
        k8s_etcd_cpu=2,
        k8s_etcd_mem="256Mi",
        vineyard_shared_mem="4Gi",
        k8s_volumes=get_k8s_volumes(),
    )
    yield sess
    sess.close()


@pytest.fixture
def gs_session_distributed():
    gs_image, gie_manager_image = get_gs_image_on_ci_env()
    sess = graphscope.session(
        num_workers=2,
        k8s_gs_image=gs_image,
        k8s_gie_graph_manager_image=gie_manager_image,
        k8s_coordinator_cpu=2,
        k8s_coordinator_mem="4Gi",
        k8s_vineyard_cpu=2,
        k8s_vineyard_mem="512Mi",
        k8s_engine_cpu=2,
        k8s_engine_mem="4Gi",
        k8s_etcd_cpu=4,
        k8s_etcd_mem="256Mi",
        vineyard_shared_mem="4Gi",
        k8s_volumes=get_k8s_volumes(),
    )
    yield sess
    sess.close()


@pytest.fixture
def data_dir():
    return "/testingdata/ldbc_sample"


@pytest.fixture
def modern_graph_data_dir():
    return "/testingdata/modern_graph"


@pytest.fixture
def p2p_property_dir():
    return "/testingdata/property"


def test_demo(gs_session, data_dir):
    graph = load_ldbc(gs_session, data_dir)

    # Interactive engine
    interactive = gs_session.gremlin(graph)
    sub_graph = interactive.subgraph(  # noqa: F841
        'g.V().hasLabel("person").outE("knows")'
    )

    # Analytical engine
    # project the projected graph to simple graph.
    simple_g = sub_graph.project(vertices={"person": []}, edges={"knows": []})

    pr_result = graphscope.pagerank(simple_g, delta=0.8)
    tc_result = graphscope.triangles(simple_g)

    # add the PageRank and triangle-counting results as new columns to the property graph
    # FIXME: Add column to sub_graph
    sub_graph.add_column(pr_result, {"Ranking": "r"})
    sub_graph.add_column(tc_result, {"TC": "r"})

    # GNN engine


def test_demo_distribute(gs_session_distributed, data_dir, modern_graph_data_dir):
    graph = load_ldbc(gs_session_distributed, data_dir)

    # Interactive engine
    interactive = gs_session_distributed.gremlin(graph)
    sub_graph = interactive.subgraph(  # noqa: F841
        'g.V().hasLabel("person").outE("knows")'
    )
    person_count = (
        interactive.execute(
            'g.V().hasLabel("person").outE("knows").bothV().dedup().count()'
        )
        .all()
        .result()[0]
    )
    knows_count = (
        interactive.execute('g.V().hasLabel("person").outE("knows").count()')
        .all()
        .result()[0]
    )
    interactive2 = gs_session_distributed.gremlin(sub_graph)
    sub_person_count = interactive2.execute("g.V().count()").all().result()[0]
    sub_knows_count = interactive2.execute("g.E().count()").all().result()[0]
    assert person_count == sub_person_count
    assert knows_count == sub_knows_count

    # Analytical engine
    # project the projected graph to simple graph.
    simple_g = sub_graph.project(vertices={"person": []}, edges={"knows": []})

    pr_result = graphscope.pagerank(simple_g, delta=0.8)
    tc_result = graphscope.triangles(simple_g)

    # add the PageRank and triangle-counting results as new columns to the property graph
    # FIXME: Add column to sub_graph
    sub_graph.add_column(pr_result, {"Ranking": "r"})
    sub_graph.add_column(tc_result, {"TC": "r"})

    # test subgraph on modern graph
    mgraph = load_modern_graph(gs_session_distributed, modern_graph_data_dir)

    # Interactive engine
    minteractive = gs_session_distributed.gremlin(mgraph)
    msub_graph = minteractive.subgraph(  # noqa: F841
        'g.V().hasLabel("person").outE("knows")'
    )
    person_count = (
        minteractive.execute(
            'g.V().hasLabel("person").outE("knows").bothV().dedup().count()'
        )
        .all()
        .result()[0]
    )
    msub_interactive = gs_session_distributed.gremlin(msub_graph)
    sub_person_count = msub_interactive.execute("g.V().count()").all().result()[0]
    assert person_count == sub_person_count

    # GNN engine


def test_multiple_session(data_dir):
    namespace = "gs-multi-" + "".join(
        [random.choice(string.ascii_lowercase) for _ in range(6)]
    )

    gs_image, gie_manager_image = get_gs_image_on_ci_env()
    sess = graphscope.session(
        num_workers=1,
        k8s_gs_image=gs_image,
        k8s_gie_graph_manager_image=gie_manager_image,
        k8s_volumes=get_k8s_volumes(),
    )
    info = sess.info
    assert info["status"] == "active"
    assert len(info["engine_hosts"].split(",")) == 1

    sess2 = graphscope.session(
        k8s_namespace=namespace,
        num_workers=2,
        k8s_gs_image=gs_image,
        k8s_gie_graph_manager_image=gie_manager_image,
        k8s_volumes=get_k8s_volumes(),
    )

    info = sess2.info
    assert info["status"] == "active"
    assert len(info["engine_hosts"].split(",")) == 2

    sess2.close()
    sess.close()


def test_query_modern_graph(gs_session, modern_graph_data_dir):
    graph = load_modern_graph(gs_session, modern_graph_data_dir)
    interactive = gs_session.gremlin(graph)
    queries = [
        "g.V().has('name','marko').count()",
        "g.V().has('person','name','marko').count()",
        "g.V().has('person','name','marko').outE('created').count()",
        "g.V().has('person','name','marko').outE('created').inV().count()",
        "g.V().has('person','name','marko').out('created').count()",
        "g.V().has('person','name','marko').out('created').values('name').count()",
    ]
    for q in queries:
        result = interactive.execute(q).all().result()[0]
        assert result == 1


def test_traversal_modern_graph(gs_session, modern_graph_data_dir):
    from gremlin_python.process.traversal import Order
    from gremlin_python.process.traversal import P

    gs_image, gie_manager_image = get_gs_image_on_ci_env()
    graph = load_modern_graph(gs_session, modern_graph_data_dir)
    interactive = gs_session.gremlin(graph)
    g = interactive.traversal_source()
    assert g.V().has("name", "marko").count().toList()[0] == 1
    assert g.V().has("person", "name", "marko").count().toList()[0] == 1
    assert g.V().has("person", "name", "marko").outE("created").count().toList()[0] == 1
    assert (
        g.V().has("person", "name", "marko").outE("created").inV().count().toList()[0]
        == 1
    )
    assert g.V().has("person", "name", "marko").out("created").count().toList()[0] == 1
    assert (
        g.V()
        .has("person", "name", "marko")
        .out("created")
        .values("name")
        .count()
        .toList()[0]
        == 1
    )
    assert (
        g.V()
        .hasLabel("person")
        .has("age", P.gt(30))
        .order()
        .by("age", Order.desc)
        .count()
        .toList()[0]
        == 2
    )


def test_add_vertices_edges(gs_session_distributed, modern_graph_data_dir):
    graph = load_modern_graph(gs_session_distributed, modern_graph_data_dir)
    graph = graph.add_vertices(
        Loader(os.path.join(modern_graph_data_dir, "person.csv"), delimiter="|"),
        "person2",
        ["name", ("age", "int")],
        "id",
    )
    assert "person2" in graph.schema.vertex_labels

    graph = graph.add_edges(
        Loader(
            os.path.join(modern_graph_data_dir, "knows.csv"),
            delimiter="|",
        ),
        "knows2",
        ["weight"],
        src_label="person2",
        dst_label="person2",
    )

    assert "knows2" in graph.schema.edge_labels

    interactive = gs_session_distributed.gremlin(graph)
    g = interactive.traversal_source()
    assert g.V().count().toList()[0] == 10
    assert g.E().count().toList()[0] == 8


def test_serialize_roundtrip(gs_session_distributed, p2p_property_dir):
    graph = gs_session_distributed.g(generate_eid=False)
    graph = graph.add_vertices(f"{p2p_property_dir}/p2p-31_property_v_0", "person")
    graph = graph.add_edges(
        f"{p2p_property_dir}/p2p-31_property_e_0",
        label="knows",
        src_label="person",
        dst_label="person",
    )

    graph.save_to("/tmp/serialize")
    new_graph = Graph.load_from("/tmp/serialize", gs_session_distributed)
    pg = new_graph.project(vertices={"person": []}, edges={"knows": ["dist"]})
    ctx = graphscope.sssp(pg, src=6)
    ret = (
        ctx.to_dataframe({"node": "v.id", "r": "r"}, vertex_range={"end": 6})
        .sort_values(by=["node"])
        .to_numpy(dtype=float)
    )
    expect = np.array(
        [[1.0, 260.0], [2.0, 229.0], [3.0, 310.0], [4.0, 256.0], [5.0, 303.0]]
    )
    assert np.all(ret == expect)
