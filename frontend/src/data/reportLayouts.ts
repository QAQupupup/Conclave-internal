/* Conclave report layouts — ported from app.html */

import {
  REPORT_DATA,
  REPORT_RESEARCH,
  REPORT_BUSINESS,
  REPORT_COMPREHENSIVE,
  REPORT_DEPLOYABLE,
} from './reportData';
import type { ProduceData } from '../types/meeting';

/* ═══ Layout spec interfaces ═══ */

export interface ReportBlock {
  type: string;
  data: Record<string, unknown>;
}

export interface ReportSection {
  id?: string;
  title: string;
  blocks: ReportBlock[];
}

export interface ReportLayout {
  type: string;
  title?: string;
  subtitle?: string;
  sections: ReportSection[];
  confidence?: Record<string, string>;
  trace?: Record<string, unknown>;
}

/* ═══ Layout Spec Generator ═══ */
/* Generates layout specs from report data — simulates what backend report_layout.py would send.
   NOTE: original app.html always used REPORT_DATA as the base `r` (meeting context providing
   clarifiedTopic / adoptedClaims / artifact ...). Each _layout* pulls its own dataset
   (REPORT_RESEARCH / REPORT_BUSINESS / ...) internally. We preserve that dispatch exactly,
   while allowing an optional `r` override. */

export function getReportLayout(type: string, r?: ProduceData): ReportLayout {
  const data = r ?? REPORT_DATA;
  switch (type) {
    case 'research_report': return _layoutResearch(data);
    case 'business_report': return _layoutBusiness(data);
    case 'comprehensive': return _layoutComprehensive(data);
    case 'deployable_service': return _layoutDeployable(data);
    case 'design_doc': return _layoutDesignDoc(data);
    case 'code_analysis': return _layoutCodeAnalysis(data);
    case 'data_science': return _layoutDataScience(data);
    case 'tested_system': return _layoutTestedSystem(data);
    default: return _layoutPrd(data);
  }
}

/* ─── Demo layouts for new types ─── */

export function _layoutDesignDoc(r: ProduceData): ReportLayout {
  return {
    type:'design_doc',
    title:'系统设计文档',subtitle:r.clarifiedTopic,
    sections:[
      {id:'overview',title:'系统概述',blocks:[
        {type:'paragraph',data:{text:'本文档描述系统的整体架构和设计决策，包括技术选型、数据模型和部署方案。'}},
      ]},
      {id:'architecture',title:'架构设计',blocks:[
        {type:'paragraph',data:{text:'采用分层架构：接入层（API Gateway）→ 应用层（微服务）→ 数据层（MySQL + Redis + Kafka）→ 基础设施层（K8s + 监控）。'}},
      ]},
      {id:'tech_stack',title:'技术选型',blocks:[
        {type:'list',data:{items:['后端：Python 3.12 + FastAPI + SQLAlchemy','前端：React 18 + TypeScript','数据库：MySQL 8.0 + Redis 7','消息队列：Kafka 3.6','容器化：Docker + Kubernetes'],ordered:false}},
      ]},
      {id:'data_model',title:'数据模型',blocks:[
        {type:'data_model',data:{entities:[
          {entity:'User',fields:['id [PK]','email','name','created_at']},
          {entity:'Order',fields:['id [PK]','user_id [FK]','status','total_amount']},
          {entity:'Product',fields:['id [PK]','name','price','stock']},
        ]}},
      ]},
      {id:'deployment',title:'部署方案',blocks:[
        {type:'code',data:{code:'# Docker Compose 部署\nversion: "3.9"\nservices:\n  api:\n    build: .\n    ports: ["8000:8000"]\n  db:\n    image: mysql:8.0\n  redis:\n    image: redis:7-alpine',lang:'YAML'}},
      ]},
      {id:'risks',title:'风险',blocks:[
        {type:'risks',data:{items:[
          {level:'high',desc:'数据库单点故障风险'},
          {level:'mid',desc:'Kafka 消息积压可能导致延迟'},
          {level:'low',desc:'前端构建时间较长（3min）'},
        ]}},
      ]},
      {id:'open_questions',title:'遗留问题',blocks:[
        {type:'list',data:{items:['是否需要引入 GraphQL 替代 REST','缓存策略：Redis TTL 还是 LRU','日志收集方案：ELK vs Loki'],ordered:false}},
      ]},
    ],
  };
}

export function _layoutCodeAnalysis(r: ProduceData): ReportLayout {
  return {
    type:'code_analysis',
    title:'代码分析报告',subtitle:r.clarifiedTopic,
    sections:[
      {id:'summary',title:'执行摘要',blocks:[
        {type:'paragraph',data:{text:'本分析通过自动化代码扫描，识别了项目中的代码质量问题、性能瓶颈和安全风险。'}},
      ]},
      {id:'analysis',title:'分析说明',blocks:[
        {type:'paragraph',data:{text:'使用 Python AST 解析器对项目源码进行静态分析，检查圈复杂度、代码重复率和潜在安全漏洞。'}},
      ]},
      {id:'code',title:'分析代码',blocks:[
        {type:'code',data:{code:'import ast\nimport os\n\ndef analyze_complexity(filepath):\n    """计算文件的圈复杂度"""\n    with open(filepath) as f:\n        tree = ast.parse(f.read())\n    complexity = 0\n    for node in ast.walk(tree):\n        if isinstance(node, (ast.If, ast.For, ast.While, ast.Try)):\n            complexity += 1\n    return complexity',lang:'PYTHON'}},
      ]},
      {id:'expected_output',title:'预期输出',blocks:[
        {type:'paragraph',data:{text:'分析完成后输出 JSON 格式报告，包含每个文件的复杂度评分、重复代码块和安全告警。'}},
      ]},
      {id:'execution',title:'执行结果',blocks:[
        {type:'code',data:{code:'{"files_analyzed": 47, "avg_complexity": 8.2, "duplicates": 3, "security_warnings": 2}',lang:'JSON'}},
      ]},
    ],
  };
}

export function _layoutDataScience(r: ProduceData): ReportLayout {
  return {
    type:'data_science',
    title:'数据分析报告',subtitle:r.clarifiedTopic,
    sections:[
      {id:'summary',title:'分析目标',blocks:[
        {type:'paragraph',data:{text:'对电商平台用户行为数据进行分析，识别高价值用户群体并预测流失风险。'}},
      ]},
      {id:'methodology',title:'方法论',blocks:[
        {type:'paragraph',data:{text:'采用 RFM 模型（Recency, Frequency, Monetary）进行用户分层，结合 XGBoost 训练流失预测模型。'}},
      ]},
      {id:'code',title:'分析代码',blocks:[
        {type:'code',data:{code:'import pandas as pd\nfrom sklearn.model_selection import train_test_split\nimport xgboost as xgb\n\n# RFM 分析\ndf["recency"] = (df["last_purchase"].max() - df["last_purchase"]).dt.days\ndf["frequency"] = df.groupby("user_id")["order_id"].transform("count")\ndf["monetary"] = df.groupby("user_id")["amount"].transform("sum")\n\n# 流失预测\nX = df[["recency", "frequency", "monetary"]]\ny = df["churned"]\nmodel = xgb.XGBClassifier(max_depth=5, learning_rate=0.1)\nmodel.fit(X_train, y_train)',lang:'PYTHON'}},
      ]},
      {id:'execution',title:'执行结果',blocks:[
        {type:'kpi_grid',data:{items:[
          {label:'模型准确率',value:'87.3',unit:'%',trend:'AUC 0.91'},
          {label:'高价值用户',value:'12,450',unit:'人',trend:'占总用户 8.2%'},
          {label:'流失风险用户',value:'3,200',unit:'人',trend:'30天内可能流失'},
          {label:'平均客单价',value:'¥487',unit:'',trend:'环比 +15.3%'},
        ]}},
      ]},
    ],
  };
}

export function _layoutTestedSystem(r: ProduceData): ReportLayout {
  return {
    type:'tested_system',
    title:'测试系统交付',subtitle:r.clarifiedTopic,
    sections:[
      {id:'summary',title:'系统说明',blocks:[
        {type:'paragraph',data:{text:'用户认证微服务，提供注册、登录、Token 刷新功能，已通过 6 项单元测试。'}},
      ]},
      {id:'prd',title:'PRD',blocks:[
        {type:'field',data:{label:'title',value:'用户认证微服务'}},
        {type:'field',data:{label:'goal',value:'提供安全的用户认证和授权功能'}},
        {type:'api_table',data:{endpoints:['POST /api/auth/register - 用户注册','POST /api/auth/login - 用户登录','POST /api/auth/refresh - Token 刷新']}},
      ]},
      {id:'main_code',title:'主代码',blocks:[
        {type:'code',data:{code:'from fastapi import FastAPI, HTTPException\nfrom pydantic import BaseModel\nimport jwt\n\napp = FastAPI()\n\nclass UserCreate(BaseModel):\n    email: str\n    password: str\n\n@app.post("/api/auth/register")\nasync def register(user: UserCreate):\n    # 注册逻辑\n    return {"id": 1, "email": user.email}\n\n@app.post("/api/auth/login")\nasync def login(user: UserCreate):\n    token = jwt.encode({"email": user.email}, "secret", algorithm="HS256")\n    return {"access_token": token}',lang:'PYTHON'}},
      ]},
      {id:'test_code',title:'测试代码',blocks:[
        {type:'code',data:{code:'import pytest\nfrom fastapi.testclient import TestClient\nfrom app import app\n\nclient = TestClient(app)\n\ndef test_register():\n    resp = client.post("/api/auth/register", json={"email": "test@example.com", "password": "123456"})\n    assert resp.status_code == 200\n\ndef test_login():\n    resp = client.post("/api/auth/login", json={"email": "test@example.com", "password": "123456"})\n    assert "access_token" in resp.json()',lang:'PYTHON'}},
      ]},
      {id:'run_command',title:'运行命令',blocks:[
        {type:'code',data:{code:'pytest test_auth.py -v',lang:'BASH'}},
      ]},
      {id:'test_results',title:'测试结果',blocks:[
        {type:'test_groups',data:{tests:[
          {name:'test_register',result:'pass',time:'0.12s'},
          {name:'test_register_duplicate',result:'pass',time:'0.08s'},
          {name:'test_login',result:'pass',time:'0.15s'},
          {name:'test_login_wrong_password',result:'pass',time:'0.09s'},
          {name:'test_refresh_token',result:'pass',time:'0.11s'},
          {name:'test_expired_token',result:'pass',time:'0.07s'},
        ]}},
      ]},
    ],
  };
}

export function _layoutPrd(r: ProduceData): ReportLayout {
  return {
    type:'prd_openapi',
    title:r.artifact.prd.title,
    subtitle:r.clarifiedTopic,
    sections:[
      {id:'summary',title:'执行摘要',blocks:[
        {type:'paragraph',data:{text:r.artifact.prd.goal}},
        {type:'list',data:{items:r.adoptedClaims,ordered:false}},
      ]},
      {id:'key_questions',title:'关键问题',blocks:[
        {type:'list',data:{items:r.keyQuestions,ordered:true}},
      ]},
      {id:'team_config',title:'团队配置',blocks:[
        {type:'team_config',data:{items:r.teamConfig.map((m)=>({role:m.role,stance:m.stance}))}},
      ]},
      {id:'conflicts',title:'冲突与裁决',blocks:[
        {type:'conflicts',data:{items:r.conflicts.map((c,i)=>({
          summary:c.summary,sideA:c.sideA,sideB:c.sideB,verdict:c.verdict,
          rationale:r.decisions.find((d)=>d.conflictId===c.id)?.rationale||c.rationale,trace:c.trace
        }))}},
      ]},
      {id:'prd',title:'最终产出 — PRD',blocks:[
        {type:'field',data:{label:'title',value:r.artifact.prd.title}},
        {type:'field',data:{label:'goal',value:r.artifact.prd.goal}},
        {type:'field',data:{label:'scope',value:r.artifact.prd.scope}},
        {type:'list',data:{items:r.artifact.prd.assumptions,ordered:false}},
        {type:'list',data:{items:r.artifact.prd.constraints,ordered:false}},
        {type:'api_table',data:{endpoints:r.artifact.prd.apiEndpoints}},
        {type:'list',data:{items:r.artifact.prd.openQuestions,ordered:false}},
      ]},
      {id:'openapi',title:'OpenAPI 规范',blocks:[
        {type:'code',data:{code:r.artifact.openapi,lang:'YAML'}},
      ]},
      {id:'attachments',title:'附件',blocks:[
        {type:'attachments',data:{items:r.artifact.attachments}},
      ]},
    ],
  };
}

export function _layoutResearch(r: ProduceData): ReportLayout {
  const d=REPORT_RESEARCH;
  return {
    type:'research_report',
    title:d.title,subtitle:d.topic,
    sections:[
      {id:'summary',title:'执行摘要',blocks:[
        {type:'paragraph',data:{text:`${d.topic}。共识别 ${d.findings.length} 项关键发现，提出 ${d.recommendations.length} 条建议。`}},
        {type:'list',data:{items:r.adoptedClaims,ordered:false}},
      ]},
      {id:'findings',title:'研究发现',blocks:[
        {type:'findings',data:{items:d.findings.map((f)=>({num:f.num,topic:f.topic,detail:f.detail,trace:f.trace,sources:f.sources}))}},
      ]},
      {id:'analysis',title:'分析',blocks:[
        {type:'paragraph',data:{text:d.analysis.join('\n\n')}},
      ]},
      {id:'recommendations',title:'建议',blocks:[
        {type:'list',data:{items:d.recommendations.map((rec)=>rec.text),ordered:true}},
      ]},
      {id:'attachments',title:'附件',blocks:[
        {type:'attachments',data:{items:d.attachments}},
      ]},
    ],
  };
}

export function _layoutBusiness(r: ProduceData): ReportLayout {
  const d=REPORT_BUSINESS;
  return {
    type:'business_report',
    title:d.title,subtitle:d.topic,
    sections:[
      {id:'summary',title:'执行摘要',blocks:[
        {type:'paragraph',data:{text:d.execSummary}},
      ]},
      {id:'kpis',title:'关键指标',blocks:[
        {type:'kpi_grid',data:{items:d.kpis.map((k)=>({label:k.label,value:k.value,unit:k.unit,trend:k.trend}))}},
      ]},
      {id:'market',title:'市场分析',blocks:[
        {type:'paragraph',data:{text:d.marketAnalysis.join('\n\n')}},
      ]},
      {id:'risks',title:'风险评估',blocks:[
        {type:'risks',data:{items:d.risks.map((risk)=>({level:risk.level,desc:risk.desc}))}},
      ]},
      {id:'timeline',title:'迁移时间线',blocks:[
        {type:'timeline',data:{items:d.timeline.map((t)=>({date:t.date,text:t.text}))}},
      ]},
      {id:'next_steps',title:'下一步行动',blocks:[
        {type:'list',data:{items:d.nextSteps,ordered:true}},
      ]},
    ],
  };
}

export function _layoutComprehensive(r: ProduceData): ReportLayout {
  const d=REPORT_COMPREHENSIVE;
  return {
    type:'comprehensive',
    title:d.title,subtitle:d.topic,
    sections:[
      {id:'requirements',title:'需求',blocks:[
        {type:'list',data:{items:d.requirements,ordered:false}},
      ]},
      {id:'system_design',title:'系统设计',blocks:[
        {type:'team_config',data:{items:d.systemDesign.map((s)=>({role:s.component,stance:`${s.tech} — ${s.desc}`}))}},
      ]},
      {id:'data_model',title:'数据模型',blocks:[
        {type:'data_model',data:{entities:d.dataModel.map((e)=>({entity:e.entity,fields:e.fields}))}},
      ]},
      {id:'api_spec',title:'API 规范',blocks:[
        {type:'code',data:{code:d.apiSpec,lang:'YAML'}},
      ]},
      {id:'attachments',title:'附件',blocks:[
        {type:'attachments',data:{items:d.attachments}},
      ]},
    ],
  };
}

export function _layoutDeployable(r: ProduceData): ReportLayout {
  const d=REPORT_DEPLOYABLE;
  return {
    type:'deployable_service',
    title:d.title,subtitle:d.topic,
    sections:[
      {id:'deploy_status',title:'部署状态',blocks:[
        {type:'field',data:{label:'服务地址',value:d.deployUrl}},
        {type:'field',data:{label:'部署时间',value:d.deployTime}},
        {type:'field',data:{label:'沙箱审查',value:d.reviewResult}},
        {type:'paragraph',data:{text:`测试 ${d.tests.length} 项${d.tests.every((t)=>t.result==='pass')?'全部通过':'有失败'}`}},
      ]},
      {id:'prd',title:'PRD',blocks:[
        {type:'field',data:{label:'title',value:d.prd.title}},
        {type:'field',data:{label:'goal',value:d.prd.goal}},
        {type:'field',data:{label:'scope',value:d.prd.scope}},
        {type:'api_table',data:{endpoints:d.prd.endpoints}},
      ]},
      {id:'code_structure',title:'代码结构',blocks:[
        {type:'file_tree',data:{items:d.fileTree.map((f)=>({name:f.name,type:f.type,indent:f.indent}))}},
      ]},
      {id:'test_results',title:'测试结果',blocks:[
        {type:'test_groups',data:{tests:d.tests.map((t)=>({name:t.name,result:t.result,time:t.time}))}},
      ]},
      {id:'dockerfile',title:'Dockerfile',blocks:[
        {type:'code',data:{code:d.dockerfile,lang:'DOCKER'}},
      ]},
    ],
  };
}


