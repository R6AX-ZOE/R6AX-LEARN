# Integration Level 使用规范

## 核心架构流程

```
用户讲解知识点 → Teaching Agent识别 → 创建虚拟图（详细内容）→ 
右侧沉淀栏显示 → 用户查看/选择 → 推送到Integration Level（节点名称）→ 
Integration与虚拟图同步
```

## 节点 (Node)

节点表示知识图谱中的概念单元，**只存储名称和掌握度**，不存储详细内容。

### 属性
- `label`: 节点名称（必填，简短准确，**不超过10个字**）
- `mastery_score`: 掌握程度 0.0-1.0（默认 0）

**重要：节点不存储description字段。详细内容应在虚拟图中存储。**

### 掌握度规则
- 初始掌握度为 0
- 完成教学标记为已掌握时，掌握度设为 30%（0.3）
- 每次习题答对，掌握度上调 5%（0.05）
- 掌握度达到 80%（0.8）时，节点显示深蓝色高亮

### 创建规范
1. 名称精确简洁，**不超过10个字**（如"sin函数"，不要"正弦函数定义及性质"）
2. **不存储description**，节点只作为知识图谱的"标签"
3. mastery_score 由系统自动管理，无需手动设置

## 虚拟图 (VirtualGraph)

虚拟图是Teaching Agent的内部数据结构，用于存储知识点的完整结构和详细内容。

### 属性
- `name`: 虚拟图名称（必填）
- `description`: 虚拟图描述（可选）
- `nodes`: 虚拟图节点列表（每个节点可以包含label、properties、content）
  - `label`: 节点名称，**不超过10个字**（简洁精确）
  - `properties`: 节点属性二元组列表 `[[属性名, 属性值], ...]`
  - `content`: 用户讲解的完整内容
- `edges`: 虚拟图内部关联关系
- `connected_nodes`: 连接到真实图谱节点的关联

### 属性二元组格式

虚拟图节点的 `properties` 字段是一个二元组列表，格式为：`[[和node的关系, 名称], ...]`

例如：
```json
{
  "label": "正弦函数",
  "properties": [
    ["定义", "对边/斜边"],
    ["值域", "[-1,1]"],
    ["周期", "2π"]
  ],
  "content": "用户讲解的完整内容..."
}
```

### 沉淀到Integration Level的表现

当虚拟图节点被推送到Integration Level时，每个二元组会表现为：

1. 创建一个子node，label为名称（如"对边/斜边"、"[-1,1]"）
2. 创建一条边，从主node连接到子node，relation为和node的关系（如"定义"、"值域"）
3. 子node的初始掌握度为0.0
4. 主node的掌握度为所有子node掌握度的平均值

**示例图谱结构：**
```
正弦函数（主node）
  ├─ 定义 → 对边/斜边（子node1）
  ├─ 值域 → [-1,1]（子node2）
  └─ 周期 → 2π（子node3）
```

### 使用场景
- Teaching Agent创建虚拟图来组织用户讲解的完整内容
- 每个虚拟图节点可以通过properties字段定义多个子node关系
- 虚拟图内容显示在teaching右侧沉淀栏供用户查看
- 用户可以选择将虚拟图节点推送到Integration Level

### 虚拟图节点搜索
- Teaching Agent可以使用 search_virtual_graph_nodes 工具在虚拟图内部查找特定知识点
- 搜索返回前5个最匹配的节点结果

## 关联 (Edge)

关联表示概念间的逻辑关系。

### 关系类型
- `prerequisite`: 前置关系（A → B：A是B的前置知识）
- `related`: 相关关系（A → B：A与B有联系但非直接依赖）
- `parent`: 父概念关系（A → B：A是B的父概念，即B是A的子概念）

### 层级结构示例
```
三角函数（父概念）
  ├─ sin（子概念）  parent: sin → 三角函数
  ├─ cos（子概念）  parent: cos → 三角函数
  ├─ tan（子概念）  parent: tan → 三角函数
  ├─ cot（子概念）  parent: cot → 三角函数
  ├─ sec（子概念）  parent: sec → 三角函数
  └─ csc（子概念）  parent: csc → 三角函数
```
注：使用 `parent` 关系，从子概念指向父概念。

### 属性
- `source_node_id`: 起始节点（必填）
- `target_node_id`: 目标节点（必填）
- `relation`: 关系类型（必填）
- `label`: 关联标签（可选，补充说明）

### 创建规范
1. 不允许自关联（source ≠ target）
2. prerequisite 从前置指向后续
3. parent 从子概念指向父概念（子 → 父）
4. label 用于解释复杂关系

## AI 工具接口

### 创建操作
- `create_graph_node`: 创建节点。参数：label, description, mastery_score（默认0）
- `create_graph_edge`: 创建关联。参数：source_label, target_label, relation, label

### 更新操作
- `update_graph_node`: 更新节点。参数：label, description, mastery_score

### 删除操作
- `delete_graph_node`: 删除节点及其关联。参数：label
- `delete_graph_edge`: 删除关联。参数：source_label, target_label

### 读取操作
- `get_graph_nodes`: 获取所有节点列表
- `get_graph_node`: 获取节点详情。参数：label
- `get_graph_edges`: 获取所有关联列表
- `get_node_edges`: 获取节点相关关联。参数：label