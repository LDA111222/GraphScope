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

import os

import numpy as np
import pytest

import graphscope
import graphscope.nx as nx
from graphscope import property_sssp
from graphscope import sssp
from graphscope.client.session import default_session
from graphscope.dataset.ldbc import load_ldbc
from graphscope.dataset.modern_graph import load_modern_graph
from graphscope.framework.graph import Graph
from graphscope.framework.loader import Loader


@pytest.fixture(scope="module")
def graphscope_session():
    graphscope.set_option(show_log=True)
    graphscope.set_option(initializing_interactive_engine=False)
    sess = graphscope.session(cluster_type="hosts")
    yield sess
    sess.close()


test_repo_dir = os.path.expandvars("${GS_TEST_DIR}")
new_property_dir = os.path.join(test_repo_dir, "new_property", "v2_e2")
property_dir = os.path.join(test_repo_dir, "property")


@pytest.fixture(scope="module")
def arrow_modern_graph(graphscope_session):
    graph = load_modern_graph(
        graphscope_session, prefix="{}/modern_graph".format(test_repo_dir)
    )
    yield graph
    graph.unload()


@pytest.fixture(scope="module")
def modern_person():
    return "{}/modern_graph/person.csv".format(test_repo_dir)


@pytest.fixture(scope="module")
def modern_software():
    return "{}/modern_graph/software.csv".format(test_repo_dir)


@pytest.fixture(scope="module")
def twitter_v_0():
    return "{}/twitter_v_0".format(new_property_dir)


@pytest.fixture(scope="module")
def modern_graph():
    return "{}/modern_graph".format(test_repo_dir)


@pytest.fixture(scope="module")
def ldbc_sample():
    return "{}/ldbc_sample".format(test_repo_dir)


@pytest.fixture(scope="module")
def p2p_property():
    return "{}/property".format(test_repo_dir)


@pytest.fixture(scope="module")
def ogbn_mag_small():
    return "{}/ogbn_mag_small".format(test_repo_dir)


@pytest.fixture(scope="module")
def twitter_v_1():
    return "{}/twitter_v_1".format(new_property_dir)


@pytest.fixture(scope="module")
def twitter_e_0_0_0():
    return "{}/twitter_e_0_0_0".format(new_property_dir)


@pytest.fixture(scope="module")
def twitter_e_0_1_0():
    return "{}/twitter_e_0_1_0".format(new_property_dir)


@pytest.fixture(scope="module")
def twitter_e_1_0_0():
    return "{}/twitter_e_1_0_0".format(new_property_dir)


@pytest.fixture(scope="module")
def twitter_e_1_1_0():
    return "{}/twitter_e_1_1_0".format(new_property_dir)


@pytest.fixture(scope="module")
def twitter_e_0_0_1():
    return "{}/twitter_e_0_0_1".format(new_property_dir)


@pytest.fixture(scope="module")
def twitter_e_0_1_1():
    return "{}/twitter_e_0_1_1".format(new_property_dir)


@pytest.fixture(scope="module")
def twitter_e_1_0_1():
    return "{}/twitter_e_1_0_1".format(new_property_dir)


@pytest.fixture(scope="module")
def twitter_e_1_1_1():
    return "{}/twitter_e_1_1_1".format(new_property_dir)


@pytest.fixture(scope="module")
def arrow_property_graph(graphscope_session):
    g = graphscope_session.g(generate_eid=False)
    g = g.add_vertices(f"{new_property_dir}/twitter_v_0", "v0")
    g = g.add_vertices(f"{new_property_dir}/twitter_v_1", "v1")
    g = g.add_edges(f"{new_property_dir}/twitter_e_0_0_0", "e0", ["weight"], "v0", "v0")
    g = g.add_edges(f"{new_property_dir}/twitter_e_0_1_0", "e0", ["weight"], "v0", "v1")
    g = g.add_edges(f"{new_property_dir}/twitter_e_1_0_0", "e0", ["weight"], "v1", "v0")
    g = g.add_edges(f"{new_property_dir}/twitter_e_1_1_0", "e0", ["weight"], "v1", "v1")
    g = g.add_edges(f"{new_property_dir}/twitter_e_0_0_1", "e1", ["weight"], "v0", "v0")
    g = g.add_edges(f"{new_property_dir}/twitter_e_0_1_1", "e1", ["weight"], "v0", "v1")
    g = g.add_edges(f"{new_property_dir}/twitter_e_1_0_1", "e1", ["weight"], "v1", "v0")
    g = g.add_edges(f"{new_property_dir}/twitter_e_1_1_1", "e1", ["weight"], "v1", "v1")

    yield g
    g.unload()


@pytest.fixture(scope="module")
def arrow_property_graph_only_from_efile(graphscope_session):
    g = graphscope_session.g(generate_eid=False)
    g = g.add_edges(f"{new_property_dir}/twitter_e_0_0_0", "e0", ["weight"], "v0", "v0")
    g = g.add_edges(f"{new_property_dir}/twitter_e_0_1_0", "e0", ["weight"], "v0", "v1")
    g = g.add_edges(f"{new_property_dir}/twitter_e_1_0_0", "e0", ["weight"], "v1", "v0")
    g = g.add_edges(f"{new_property_dir}/twitter_e_1_1_0", "e0", ["weight"], "v1", "v1")
    g = g.add_edges(f"{new_property_dir}/twitter_e_0_0_1", "e1", ["weight"], "v0", "v0")
    g = g.add_edges(f"{new_property_dir}/twitter_e_0_1_1", "e1", ["weight"], "v0", "v1")
    g = g.add_edges(f"{new_property_dir}/twitter_e_1_0_1", "e1", ["weight"], "v1", "v0")
    g = g.add_edges(f"{new_property_dir}/twitter_e_1_1_1", "e1", ["weight"], "v1", "v1")

    yield g
    g.unload()


@pytest.fixture(scope="module")
def arrow_property_graph_undirected(graphscope_session):
    g = graphscope_session.g(directed=False, generate_eid=False)
    g = g.add_vertices(f"{new_property_dir}/twitter_v_0", "v0")
    g = g.add_vertices(f"{new_property_dir}/twitter_v_1", "v1")
    g = g.add_edges(f"{new_property_dir}/twitter_e_0_0_0", "e0", ["weight"], "v0", "v0")
    g = g.add_edges(f"{new_property_dir}/twitter_e_0_1_0", "e0", ["weight"], "v0", "v1")
    g = g.add_edges(f"{new_property_dir}/twitter_e_1_0_0", "e0", ["weight"], "v1", "v0")
    g = g.add_edges(f"{new_property_dir}/twitter_e_1_1_0", "e0", ["weight"], "v1", "v1")
    g = g.add_edges(f"{new_property_dir}/twitter_e_0_0_1", "e1", ["weight"], "v0", "v0")
    g = g.add_edges(f"{new_property_dir}/twitter_e_0_1_1", "e1", ["weight"], "v0", "v1")
    g = g.add_edges(f"{new_property_dir}/twitter_e_1_0_1", "e1", ["weight"], "v1", "v0")
    g = g.add_edges(f"{new_property_dir}/twitter_e_1_1_1", "e1", ["weight"], "v1", "v1")

    yield g
    g.unload()


@pytest.fixture(scope="module")
def arrow_property_graph_lpa(graphscope_session):
    g = graphscope_session.g(generate_eid=False)
    g = g.add_vertices(f"{property_dir}/lpa_dataset/lpa_3000_v_0", "v0")
    g = g.add_vertices(f"{property_dir}/lpa_dataset/lpa_3000_v_1", "v1")
    g = g.add_edges(
        f"{property_dir}/lpa_dataset/lpa_3000_e_0", "e0", ["weight"], "v0", "v1"
    )
    yield g
    g.unload()


@pytest.fixture(scope="module")
def arrow_project_graph(arrow_property_graph):
    pg = arrow_property_graph.project(vertices={"v0": ["id"]}, edges={"e0": ["weight"]})
    yield pg


@pytest.fixture(scope="module")
def arrow_project_undirected_graph(arrow_property_graph_undirected):
    pg = arrow_property_graph_undirected.project(
        vertices={"v0": ["id"]}, edges={"e0": ["weight"]}
    )
    yield pg


@pytest.fixture(scope="module")
def p2p_property_graph(graphscope_session):
    g = graphscope_session.g(generate_eid=False)
    g = g.add_vertices(f"{property_dir}/p2p-31_property_v_0", "person")
    g = g.add_edges(
        f"{property_dir}/p2p-31_property_e_0",
        label="knows",
        src_label="person",
        dst_label="person",
    )
    yield g
    g.unload()


@pytest.fixture(scope="module")
def p2p_property_graph_string(graphscope_session):
    g = graphscope_session.g(oid_type="string", generate_eid=False)
    g = g.add_vertices(f"{property_dir}/p2p-31_property_v_0", "person")
    g = g.add_edges(
        f"{property_dir}/p2p-31_property_e_0",
        label="knows",
        src_label="person",
        dst_label="person",
    )
    yield g
    g.unload()


@pytest.fixture(scope="module")
def p2p_property_graph_undirected(graphscope_session):
    g = graphscope_session.g(directed=False, generate_eid=False)
    g = g.add_vertices(f"{property_dir}/p2p-31_property_v_0", "person")
    g = g.add_edges(
        f"{property_dir}/p2p-31_property_e_0",
        label="knows",
        src_label="person",
        dst_label="person",
    )
    yield g
    g.unload()


@pytest.fixture(scope="module")
def p2p_project_directed_graph(p2p_property_graph):
    pg = p2p_property_graph.project(
        vertices={"person": ["weight"]}, edges={"knows": ["dist"]}
    )
    yield pg


@pytest.fixture(scope="module")
def p2p_project_undirected_graph(p2p_property_graph_undirected):
    pg = p2p_property_graph_undirected.project(
        vertices={"person": ["weight"]}, edges={"knows": ["dist"]}
    )
    yield pg


@pytest.fixture(scope="module")
def p2p_project_directed_graph_string(p2p_property_graph_string):
    pg = p2p_property_graph_string.project(
        vertices={"person": ["weight"]}, edges={"knows": ["dist"]}
    )
    yield pg


@pytest.fixture(scope="module")
def projected_pg_no_edge_data(arrow_property_graph):
    pg = arrow_property_graph.project(vertices={"v0": []}, edges={"e0": []})
    yield pg


@pytest.fixture(scope="module")
def dynamic_property_graph(graphscope_session):
    with default_session(graphscope_session):
        g = nx.Graph()
    g.add_edges_from([(1, 2), (2, 3)], weight=3)
    yield g


@pytest.fixture(scope="module")
def dynamic_project_graph(graphscope_session):
    with default_session(graphscope_session):
        g = nx.Graph()
    g.add_edges_from([(1, 2), (2, 3)], weight=3)
    pg = g.project_to_simple(e_prop="weight")
    yield pg


@pytest.fixture(scope="module")
def arrow_empty_graph(property_dir=os.path.expandvars("${GS_TEST_DIR}/property")):
    return None


@pytest.fixture(scope="module")
def append_only_graph():
    return None


@pytest.fixture(scope="module")
def sssp_result():
    ret = {}
    ret["directed"] = np.loadtxt(
        "{}/ldbc/p2p-31-SSSP-directed".format(property_dir), dtype=float
    )
    ret["undirected"] = np.loadtxt(
        "{}/ldbc/p2p-31-SSSP".format(property_dir), dtype=float
    )
    yield ret


@pytest.fixture(scope="module")
def wcc_result():
    ret = np.loadtxt("{}/../p2p-31-wcc_auto".format(property_dir), dtype=int)
    yield ret


@pytest.fixture(scope="module")
def kshell_result():
    ret = np.loadtxt("{}/../p2p-31-kshell-3".format(property_dir), dtype=int)
    yield ret


@pytest.fixture(scope="module")
def pagerank_result():
    ret = {}
    ret["directed"] = np.loadtxt(
        "{}/ldbc/p2p-31-PR-directed".format(property_dir), dtype=float
    )
    ret["undirected"] = np.loadtxt(
        "{}/ldbc/p2p-31-PR".format(property_dir), dtype=float
    )
    yield ret


@pytest.fixture(scope="module")
def bfs_result():
    ret = {}
    ret["directed"] = np.loadtxt(
        "{}/ldbc/p2p-31-BFS-directed".format(property_dir), dtype=int
    )
    ret["undirected"] = np.loadtxt("{}/ldbc/p2p-31-BFS".format(property_dir), dtype=int)
    yield ret


@pytest.fixture(scope="module")
def cdlp_result():
    ret = np.loadtxt("{}/ldbc/p2p-31-CDLP".format(property_dir), dtype=int)
    yield ret


@pytest.fixture(scope="module")
def clustering_result():
    ret = np.fromfile(
        "{}/results/twitter_property_clustering_ndarray".format(property_dir), sep="\n"
    )
    yield ret


@pytest.fixture(scope="module")
def dc_result():
    ret = np.fromfile(
        "{}/results/twitter_property_dc_ndarray".format(property_dir), sep="\n"
    )
    yield ret


@pytest.fixture(scope="module")
def ev_result():
    ret = np.fromfile(
        "{}/results/twitter_property_ev_ndarray".format(property_dir), sep="\n"
    )
    yield ret


@pytest.fixture(scope="module")
def katz_result():
    ret = np.fromfile(
        "{}/results/twitter_property_katz_ndarray".format(property_dir), sep="\n"
    )
    yield ret


@pytest.fixture(scope="module")
def triangles_result():
    ret = np.fromfile(
        "{}/results/twitter_property_triangles_ndarray".format(property_dir),
        dtype=np.int64,
        sep="\n",
    )
    yield ret


@pytest.fixture(scope="module")
def property_context(arrow_property_graph):
    return property_sssp(arrow_property_graph, 20)


@pytest.fixture(scope="module")
def simple_context(arrow_property_graph):
    sg = arrow_property_graph.project(vertices={"v0": ["id"]}, edges={"e0": ["weight"]})
    return sssp(sg, 20)


@pytest.fixture(scope="module")
def ldbc_graph(graphscope_session):
    graph = load_ldbc(graphscope_session, prefix="{}/ldbc_sample".format(test_repo_dir))
    yield graph
    graph.unload()
