from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
triads = []


@app.route("/get_children", methods=["GET"])
def get_children():
    try:
        node = request.args.get("node")
        children = decision_tree.get(node, {})
        children_list = [{"question": item[0], "answer": item[1]} for item in list(children.items())]
        return jsonify({"root": node, "children": children_list})
    except Exception as e:
        return jsonify({"error": str(e)})


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
            children_list = [{"question": item[0], "answer": item[1]} for item in list(decision_tree.get(start_node, {}).items())]
            return {"root": start_node, "children": children_list}

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


@app.route("/load_triads", methods=["POST"])
def load_triads():
    try:
        uploaded_file = request.files["file"]
        if uploaded_file.filename != "":
            triads.clear()
            for line in uploaded_file:
                triad = line.decode("utf-8").strip()
                triads.append(triad)

            global decision_tree
            decision_tree = build_decision_tree(triads)

            return jsonify(find_root_node(triads))
        else:
            return jsonify({"error": "No file uploaded."})
    except Exception as e:
        return jsonify({"error": str(e)})


if __name__ == "__main__":
    app.run(debug=True)
