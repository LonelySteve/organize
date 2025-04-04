from typing import Any, Dict, List

# 定义 Node 结构：
#   name: 节点名称
#   dependOn: 依赖的节点名称列表
#   match: 无参数的函数，返回 bool 表示是否匹配
Node = Dict[str, Any]  # 其中 "match" 的类型为 Callable[[], bool]


def is_cyclic(node_map: List[Node]) -> bool:
    """
    使用标准 Kahn 算法判断图中是否存在环（忽略 match 条件）。
    """
    # 建立节点映射
    nodes: Dict[str, Node] = {node["name"]: node for node in node_map}
    in_degree: Dict[str, int] = {name: 0 for name in nodes}
    children: Dict[str, List[str]] = {name: [] for name in nodes}

    for node in nodes.values():
        for dep in node.get("dependOn", []):
            if dep in nodes:
                in_degree[node["name"]] += 1
                children[dep].append(node["name"])

    # Kahn 算法：收集所有入度为 0 的节点，然后逐步删除依赖边
    queue: List[str] = [name for name, deg in in_degree.items() if deg == 0]
    visited_count = 0

    while queue:
        current = queue.pop(0)
        visited_count += 1
        for child in children[current]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    return visited_count != len(nodes)


def find_matching_path(node_map: List[Node]) -> List[str] | None:
    """
    从所有入度为 0 的节点开始，每一层只从匹配的节点出发向下广度遍历。
    若某层没有匹配节点，则停止遍历，返回已匹配的节点列表。
    如果图存在环（无论节点是否匹配），则返回 None。
    """
    # 先检测整个图是否有环
    if is_cyclic(node_map):
        return None

    # 建立节点名称 -> 节点对象的映射
    nodes: Dict[str, Node] = {node["name"]: node for node in node_map}

    # 初始化每个节点的入度和反向依赖（children）
    in_degree: Dict[str, int] = {name: 0 for name in nodes}
    children: Dict[str, List[str]] = {name: [] for name in nodes}

    for node in nodes.values():
        for dep in node.get("dependOn", []):
            if dep in nodes:
                in_degree[node["name"]] += 1
                children[dep].append(node["name"])

    result: List[str] = []
    # 初始起始节点：所有入度为 0 的节点（无依赖节点）
    current_round: List[str] = [name for name, deg in in_degree.items() if deg == 0]

    # 每一轮只从匹配的起始节点出发继续向下遍历
    while current_round:
        next_round: List[str] = []
        round_matched: List[str] = []
        for name in current_round:
            node = nodes[name]
            if node["match"]():
                round_matched.append(name)
                # 只有匹配的节点才能“激活”其后继节点
                for child in children[name]:
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        next_round.append(child)
            # 如果当前节点不匹配，则其后继不被考虑
        if round_matched:
            result.extend(round_matched)
            current_round = next_round
        else:
            # 当前层没有匹配的节点，则停止遍历
            break

    return result


# ---------------------------
# 以下为多个测试案例
# ---------------------------
if __name__ == "__main__":
    # 测试案例 1: 原测试案例
    # 图：base -> foo -> never，其中 base 和 foo 不匹配，never 匹配
    # 预期：由于起始节点 base 不匹配，后续节点不被遍历，结果应为空列表
    node_map1 = [
        {"name": "base", "dependOn": [], "match": lambda: False},
        {"name": "foo", "dependOn": ["base"], "match": lambda: False},
        {"name": "never", "dependOn": ["foo"], "match": lambda: True},
    ]
    result1 = find_matching_path(node_map1)
    print("Test1:", result1)  # Expected: []

    # 测试案例 2: 单个节点匹配
    # 图：只有一个节点 A，无依赖且匹配
    node_map2 = [
        {"name": "A", "dependOn": [], "match": lambda: True},
    ]
    result2 = find_matching_path(node_map2)
    print("Test2:", result2)  # Expected: ["A"]

    # 测试案例 3: 连续链路全部匹配
    # 图：A -> B -> C，均匹配
    node_map3 = [
        {"name": "A", "dependOn": [], "match": lambda: True},
        {"name": "B", "dependOn": ["A"], "match": lambda: False},
        {"name": "C", "dependOn": ["A", "B"], "match": lambda: True},
    ]
    result3 = find_matching_path(node_map3)
    print("Test3:", result3)  # Expected: ["A", "B", "C"]

    # 测试案例 4: 连续链路中间节点不匹配，中断传递
    # 图：A -> B -> C，A 匹配，B 不匹配（因此 C 不会被遍历，即使 C 匹配）
    node_map4 = [
        {"name": "A", "dependOn": [], "match": lambda: True},
        {"name": "B", "dependOn": ["A"], "match": lambda: False},
        {"name": "C", "dependOn": ["B"], "match": lambda: True},
    ]
    result4 = find_matching_path(node_map4)
    print("Test4:", result4)  # Expected: ["A"]

    # 测试案例 5: 分支结构
    # 图结构：
    #         A
    #       /   \
    #      B     C
    #     / \
    #    D   E
    # 设 A、B、E 匹配，C 不匹配，D 匹配，但由于 D 依赖 B(匹配)和 C(不匹配)的问题，
    # 实际上 D 的入度不会降为 0（因为 C 不匹配，所以其依赖不会传递），因此 D 不被遍历。
    node_map5 = [
        {"name": "A", "dependOn": [], "match": lambda: True},
        {"name": "B", "dependOn": ["A"], "match": lambda: True},
        {"name": "C", "dependOn": ["A"], "match": lambda: False},
        {"name": "D", "dependOn": ["B", "C"], "match": lambda: True},
        {"name": "E", "dependOn": ["B"], "match": lambda: True},
    ]
    result5 = find_matching_path(node_map5)
    print("Test5:", result5)  # Expected: ["A", "B", "E"]

    # 测试案例 6: 图中存在环
    # 图：A <-> B（互相依赖），两者均匹配
    node_map6 = [
        {"name": "A", "dependOn": ["B"], "match": lambda: True},
        {"name": "B", "dependOn": ["A"], "match": lambda: True},
    ]
    result6 = find_matching_path(node_map6)
    print("Test6:", result6)  # Expected: None (存在环)

    # 测试案例 7: 环与分支混合
    # 图结构：
    #       A
    #       |
    #       B
    #      / \
    #     C - D   (C 与 D 构成环)
    # A 和 B 匹配，C 和 D 均匹配
    node_map7 = [
        {"name": "A", "dependOn": [], "match": lambda: True},
        {"name": "B", "dependOn": ["A"], "match": lambda: True},
        {"name": "C", "dependOn": ["B", "D"], "match": lambda: True},
        {"name": "D", "dependOn": ["C"], "match": lambda: True},
    ]
    result7 = find_matching_path(node_map7)
    print("Test7:", result7)  # Expected: None (存在环)
