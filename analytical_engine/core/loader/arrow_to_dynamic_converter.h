/** Copyright 2020 Alibaba Group Holding Limited.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * 	http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#ifndef ANALYTICAL_ENGINE_CORE_LOADER_ARROW_TO_DYNAMIC_CONVERTER_H_
#define ANALYTICAL_ENGINE_CORE_LOADER_ARROW_TO_DYNAMIC_CONVERTER_H_

#ifdef NETWORKX

#include <memory>
#include <string>
#include <unordered_set>
#include <vector>

#include "vineyard/graph/fragment/arrow_fragment.h"

namespace gs {
/**
 * @brief A utility class to pack basic C++ data type to folly::dynamic
 * @tparam T
 */
template <typename T>
struct DynamicWrapper {
  static folly::dynamic to_dynamic(T e) { return folly::dynamic(e); }
};

/**
 * @brief This is a specialized DynamicWrapper for arrow::util::string_view type
 */
template <>
struct DynamicWrapper<std::string> {
  static folly::dynamic to_dynamic(arrow::util::string_view e) {
    return folly::dynamic(e.to_string());
  }
};
/**
 * @brief A ArrowFragment to DynamicFragment converter. The conversion is
 * proceeded by traversing the source graph.
 * @tparam FRAG_T Fragment class
 */
template <typename FRAG_T>
class ArrowToDynamicConverter {
  using src_fragment_t = FRAG_T;
  using oid_t = typename src_fragment_t::oid_t;
  using label_id_t = typename src_fragment_t::label_id_t;
  using dst_fragment_t = DynamicFragment;
  using vertex_map_t = typename dst_fragment_t::vertex_map_t;
  using vid_t = typename dst_fragment_t::vid_t;
  using vdata_t = typename dst_fragment_t::vdata_t;
  using edata_t = typename dst_fragment_t::edata_t;

 public:
  explicit ArrowToDynamicConverter(const grape::CommSpec& comm_spec)
      : comm_spec_(comm_spec) {}

  bl::result<std::shared_ptr<dst_fragment_t>> Convert(
      const std::shared_ptr<src_fragment_t>& arrow_frag) {
    auto arrow_vm = arrow_frag->GetVertexMap();
    BOOST_LEAF_AUTO(dynamic_vm, convertVertexMap(arrow_vm));
    BOOST_LEAF_AUTO(dynamic_frag, convertFragment(arrow_frag, dynamic_vm));
    return dynamic_frag;
  }

 private:
  bl::result<void> extractProperty(const std::shared_ptr<arrow::Table>& table,
                                   int64_t row_id, int col_id,
                                   folly::dynamic& data) {
    auto column = table->column(col_id);
    auto type = column->type();
    auto prop_key = table->field(col_id)->name();

    CHECK_LE(column->num_chunks(), 1);
    if (data.find(prop_key) != data.items().end()) {
      RETURN_GS_ERROR(vineyard::ErrorCode::kIllegalStateError,
                      "Duplicated key " + prop_key);
    }
    if (type == arrow::int32()) {
      auto array =
          std::dynamic_pointer_cast<arrow::Int32Array>(column->chunk(0));
      data[prop_key] = array->Value(row_id);
    } else if (type == arrow::int64()) {
      auto array =
          std::dynamic_pointer_cast<arrow::Int64Array>(column->chunk(0));
      data[prop_key] = array->Value(row_id);
    } else if (type == arrow::uint32()) {
      auto array =
          std::dynamic_pointer_cast<arrow::UInt32Array>(column->chunk(0));
      data[prop_key] = array->Value(row_id);
    } else if (type == arrow::uint64()) {
      auto array =
          std::dynamic_pointer_cast<arrow::UInt64Array>(column->chunk(0));
      data[prop_key] = array->Value(row_id);
    } else if (type == arrow::float32()) {
      auto array =
          std::dynamic_pointer_cast<arrow::FloatArray>(column->chunk(0));
      data[prop_key] = array->Value(row_id);
    } else if (type == arrow::float64()) {
      auto array =
          std::dynamic_pointer_cast<arrow::DoubleArray>(column->chunk(0));
      data[prop_key] = array->Value(row_id);
    } else if (type == arrow::utf8()) {
      auto array =
          std::dynamic_pointer_cast<arrow::StringArray>(column->chunk(0));
      data[prop_key] = array->GetString(row_id);
    } else if (type == arrow::large_utf8()) {
      auto array =
          std::dynamic_pointer_cast<arrow::LargeStringArray>(column->chunk(0));
      data[prop_key] = array->GetString(row_id);
    } else {
      RETURN_GS_ERROR(vineyard::ErrorCode::kDataTypeError,
                      "Unexpected type: " + type->ToString());
    }
    return {};
  }

  bl::result<std::shared_ptr<vertex_map_t>> convertVertexMap(
      const std::shared_ptr<typename src_fragment_t::vertex_map_t>&
          src_vm_ptr) {
    auto fnum = src_vm_ptr->fnum();
    auto dst_vm_ptr = std::make_shared<vertex_map_t>(comm_spec_);

    CHECK(src_vm_ptr->fnum() == comm_spec_.fnum());
    dst_vm_ptr->Init();

    vineyard::IdParser<vid_t> id_parser;

    id_parser.Init(fnum, src_vm_ptr->label_num());

    for (label_id_t v_label = 0; v_label < src_vm_ptr->label_num(); v_label++) {
      for (fid_t fid = 0; fid < fnum; fid++) {
        for (vid_t offset = 0;
             offset < src_vm_ptr->GetInnerVertexSize(fid, v_label); offset++) {
          auto gid = id_parser.GenerateId(fid, v_label, offset);
          typename vineyard::InternalType<oid_t>::type oid;

          CHECK(src_vm_ptr->GetOid(gid, oid));
          if (!dst_vm_ptr->AddVertex(
                  fid, DynamicWrapper<oid_t>::to_dynamic(oid), gid)) {
            std::stringstream ss;
            ss << "Duplicated oid " << oid;
            RETURN_GS_ERROR(vineyard::ErrorCode::kDataTypeError, ss.str());
          }
        }
      }
    }
    dst_vm_ptr->Construct();

    return dst_vm_ptr;
  }

  bl::result<std::shared_ptr<dst_fragment_t>> convertFragment(
      const std::shared_ptr<src_fragment_t>& src_frag,
      const std::shared_ptr<vertex_map_t>& dst_vm) {
    auto fid = src_frag->fid();
    std::vector<grape::internal::Vertex<vid_t, vdata_t>> processed_vertices;

    for (label_id_t v_label = 0; v_label < src_frag->vertex_label_num();
         v_label++) {
      auto v_data = src_frag->vertex_data_table(v_label);

      // traverse vertices and extract data from ArrowFragment
      for (const auto& u : src_frag->InnerVertices(v_label)) {
        auto oid = src_frag->GetId(u);
        vid_t gid;

        CHECK(dst_vm->GetGid(fid, oid, gid));
        folly::dynamic data = folly::dynamic::object();
        for (auto col_id = 0; col_id < v_data->num_columns(); col_id++) {
          auto column = v_data->column(col_id);
          auto prop_key = v_data->field(col_id)->name();
          auto type = column->type();

          if (data.find(prop_key) != data.items().end()) {
            RETURN_GS_ERROR(vineyard::ErrorCode::kDataTypeError,
                            "Duplicated key " + prop_key);
          }
          if (type == arrow::int32()) {
            data[prop_key] = src_frag->template GetData<int32_t>(u, col_id);
          } else if (type == arrow::int64()) {
            data[prop_key] = src_frag->template GetData<int64_t>(u, col_id);
          } else if (type == arrow::uint32()) {
            data[prop_key] = src_frag->template GetData<uint32_t>(u, col_id);
          } else if (type == arrow::uint64()) {
            data[prop_key] = src_frag->template GetData<uint64_t>(u, col_id);
          } else if (type == arrow::float32()) {
            data[prop_key] = src_frag->template GetData<float>(u, col_id);
          } else if (type == arrow::float64()) {
            data[prop_key] = src_frag->template GetData<double>(u, col_id);
          } else if (type == arrow::utf8()) {
            data[prop_key] = src_frag->template GetData<std::string>(u, col_id);
          } else if (type == arrow::large_utf8()) {
            data[prop_key] = src_frag->template GetData<std::string>(u, col_id);
          } else {
            RETURN_GS_ERROR(vineyard::ErrorCode::kDataTypeError,
                            "Unexpected type: " + type->ToString());
          }
        }
        processed_vertices.emplace_back(gid, data);
      }
    }

    std::vector<grape::Edge<vid_t, edata_t>> processed_edges;
    // traverse edges and extract data
    for (label_id_t v_label = 0; v_label < src_frag->vertex_label_num();
         v_label++) {
      for (const auto& u : src_frag->InnerVertices(v_label)) {
        auto u_oid = src_frag->GetId(u);
        vid_t u_gid;
        CHECK(dst_vm->GetGid(fid, u_oid, u_gid));
        std::unordered_set<vid_t> existed_dsts;

        for (label_id_t e_label = 0; e_label < src_frag->edge_label_num();
             e_label++) {
          auto oe = src_frag->GetOutgoingAdjList(u, e_label);
          auto e_data = src_frag->edge_data_table(e_label);

          for (auto& e : oe) {
            auto v = e.neighbor();
            auto e_id = e.edge_id();
            auto v_oid = src_frag->GetId(v);
            vid_t v_gid;
            CHECK(dst_vm->GetGid(v_oid, v_gid));

            // detect parallel edge of different label on the property graph
            if (existed_dsts.find(v_gid) != existed_dsts.end()) {
              std::stringstream ss;
              ss << "Duplicated edge: " << u_oid << " -> " << v_oid;
              RETURN_GS_ERROR(vineyard::ErrorCode::kIllegalStateError,
                              ss.str());
            }
            existed_dsts.insert(v_gid);

            folly::dynamic data = folly::dynamic::object();
            for (auto col_id = 0; col_id < e_data->num_columns(); col_id++) {
              BOOST_LEAF_CHECK(extractProperty(e_data, e_id, col_id, data));
            }
            processed_edges.emplace_back(u_gid, v_gid, data);
          }
        }
      }
    }

    auto dynamic_frag = std::make_shared<dst_fragment_t>(dst_vm);
    dynamic_frag->Init(src_frag->fid(), processed_vertices, processed_edges,
                       src_frag->directed());
    return dynamic_frag;
  }

  grape::CommSpec comm_spec_;
};

}  // namespace gs
#endif
#endif  // ANALYTICAL_ENGINE_CORE_LOADER_ARROW_TO_DYNAMIC_CONVERTER_H_
