import json


def build_decision_tree(triads):
    decision_tree = {}

    for triad in triads:
        start_node, link, target_node = triad.split("\t")

        if start_node not in decision_tree:
            decision_tree[start_node] = {}

        decision_tree[start_node][link] = target_node

    return decision_tree


def find_root_node(triads):
    target_nodes = set()

    for triad in triads:
        start_node, link, target_node = triad.split("\t")
        target_nodes.add(target_node)

    for triad in triads:
        start_node, _, _ = triad.split("\t")
        if start_node not in target_nodes:
            return start_node

    return None


def traverse_decision_tree(decision_tree, triads):
    current_node = find_root_node(triads)

    while True:
        print(f"Current node: {current_node}")
        choices = decision_tree.get(current_node, {})

        if not choices:
            print("Reached a leaf node.")
            break

        print("Available choices:")
        for i, (link, target_node) in enumerate(choices.items(), start=1):
            print(f"{i}. {link}")

        choice = input("Enter your choice (1, 2, ...): ")
        try:
            choice = int(choice)
            link = list(choices.keys())[choice - 1]
            current_node = choices[link]
        except (ValueError, IndexError):
            print("Invalid choice. Please enter a valid number.")


def read_triads_from_file(filename):
    triads = []
    with open(filename, 'r') as file:
        for line in file:
            triad = line.strip()
            triads.append(triad)
    return triads


if __name__ == "__main__":
    filename = "triads.txt"
    triads = read_triads_from_file(filename)

    decision_tree = build_decision_tree(triads)
    traverse_decision_tree(decision_tree, triads)
