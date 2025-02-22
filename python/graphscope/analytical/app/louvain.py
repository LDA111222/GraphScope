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

from graphscope.framework.app import AppAssets
from graphscope.framework.app import not_compatible_for
from graphscope.framework.app import project_to_simple
from graphscope.framework.errors import InvalidArgumentError

__all__ = [
    "louvain",
]


@project_to_simple
@not_compatible_for("arrow_property", "dynamic_property")
def louvain(graph, min_progress=1000, progress_tries=1):
    """Compute best partition on the `graph` by louvain.

    Args:
        graph (:class:`Graph`): A projected simple graph.
        min_progress: The minimum delta X required to be considered progress, where X is the number of nodes
                      that have changed their community on a particular pass.
                      Delta X is then the difference in number of nodes that changed communities
                      on the current pass compared to the previous pass.
        progress_tries: number of times the min_progress setting is not met
                        before exiting form the current level and compressing the graph.


    Returns:
        :class:`VertexDataContext`: A context with each vertex assigned with id of community it belongs to.

    References:
        [1] Blondel, V.D. et al. Fast unfolding of communities in large networks. J. Stat. Mech 10008, 1-12(2008).

        [2] https://github.com/Sotera/distributed-graph-analytics

        [3] https://sotera.github.io/distributed-graph-analytics/louvain/

    Examples:

    .. code:: python

        import graphscope as gs
        s = gs.session()
        g = s.load_from('The parameters for loading a graph...')
        pg = g.project(vertices={"vlabel": []}, edges={"elabel": ["weight"]})
        r = gs.louvain(pg)
        s.close()

    """
    if graph.is_directed():
        raise InvalidArgumentError("Louvain not support directed graph.")
    return AppAssets(algo="louvain")(graph, min_progress, progress_tries)
