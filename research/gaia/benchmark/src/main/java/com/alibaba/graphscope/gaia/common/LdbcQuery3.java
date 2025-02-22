/**
 * Copyright 2020 Alibaba Group Holding Limited.
 * 
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 * 
 *     http://www.apache.org/licenses/LICENSE-2.0
 * 
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package com.alibaba.graphscope.gaia.common;

import org.apache.tinkerpop.gremlin.driver.Result;
import org.apache.tinkerpop.gremlin.structure.Vertex;

import java.util.HashMap;
import java.util.Map;

public class LdbcQuery3 extends AbstractLdbcWithSubQuery {
    public LdbcQuery3(String queryName, String queryFile, String parameterFile) throws Exception {
        super(queryName, queryFile, parameterFile);
    }

    @Override
    String generateGremlinQuery(HashMap<String, String> singleParameter,
                                String gremlinQueryPattern) {
        singleParameter.put("startDate",  transformDate(singleParameter.get("startDate")));
        String endDate = getEndDate(singleParameter.get("startDate"), singleParameter.get("durationDays"));
        singleParameter.put("endDate", endDate);
        for (String parameter : singleParameter.keySet()) {
            gremlinQueryPattern = gremlinQueryPattern.replace(
                    getParameterPrefix() + parameter + getParameterPostfix(),
                    singleParameter.get(parameter)
            );
        }
        return gremlinQueryPattern;
    }

    @Override
    String buildSubQuery(Result result, HashMap<String, String> singleParameter) {
        Map.Entry<Vertex, Long> entry = (Map.Entry) result.getObject();
        singleParameter.put("startDate",  transformDate(singleParameter.get("startDate")));
        String startDate = singleParameter.get("startDate");
        String endDate = getEndDate(startDate, singleParameter.get("durationDays"));
        String countryY = singleParameter.get("countryYName");

        return String.format("g.V(%s).in('HASCREATOR').has('creationDate',inside(%s,%s)).filter(__.out('ISLOCATEDIN').has('name',eq('%s'))).count()",
                entry.getKey().toString(),
                startDate,
                endDate,
                countryY);
    }
}
