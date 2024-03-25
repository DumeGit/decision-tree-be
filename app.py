from flask import Flask, request, jsonify
from flask_cors import CORS
import xml.etree.ElementTree as ET

app = Flask(__name__)
CORS(app)
triads = []
entities = {}
links = {}

@app.route("/get_children", methods=["GET"])
def get_children():
    try:
        node = request.args.get("node")
        children_list = [{"question": {'id': item[1], 'label': entities[item[1]]},
                          "answer": {'id': item[0], 'label': links[item[0]].get('label')}} for item in
                         list(decision_tree.get(node, {}).items())]
        return jsonify({"root": {'id': node, 'label': entities.get(node)}, "children": children_list})
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
            children_list = [{"question": item[0], "answer": item[1]} for item in
                             list(decision_tree.get(start_node, {}).items())]
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
            entities, links = parse_ivml(uploaded_file)
            global decision_tree
            decision_tree = build_decision_tree_ivml(links)
            return jsonify(find_root_node_ivml(entities, links))
        else:
            return jsonify({"error": "No file uploaded."})
    except Exception as e:
        return jsonify({"error": str(e)})


def parse_ivml(file_path):
    tree = ET.parse(file_path)
    root = tree.getroot()

    # Extract entities
    for entity in root.findall('.//{urn:ivml}entity'):
        entity_id = entity.get('id')
        label = entity.get('label')
        # Process other properties as needed
        entities[entity_id] = label

    # Extract links
    for link in root.findall('.//{urn:ivml}link'):
        link_id = link.get('id')
        from_id = link.get('from')
        to_id = link.get('to')
        label = link.get('label')
        # Process other properties as needed
        links[link_id] = ({'from_id': from_id, 'to_id': to_id, 'label': label})

    return entities, links


# Example usage

def build_decision_tree_ivml(links):
    decision_tree = {}
    for id, data in links.items():
        if data.get('from_id') not in decision_tree:
            decision_tree[data.get('from_id')] = {}

        decision_tree[data.get('from_id')][id] = data.get('to_id')

    # for entity_id, label in entities.items():
    #    if entity_id not in decision_tree_ivml:
    #        decision_tree_ivml[entity_id] = {}

    #    decision_tree_ivml[entity_id]['label'] = label

    return decision_tree


def find_root_node_ivml(entities, links):
    target_nodes = set(data.get('to_id') for _, data in links.items())

    for entity_id, _ in entities.items():
        if entity_id not in target_nodes:
            children_list = [{"question": {'id': item[1], 'label': entities[item[1]]}, "answer": {'id': item[0], 'label': links[item[0]].get('label')}} for item in
                             list(decision_tree.get(entity_id, {}).items())]
            return {"root": {'id': entity_id, 'label': entities[entity_id]}, "children": children_list}

    return None


# Example usage


if __name__ == "__main__":
    app.run(debug=True)
