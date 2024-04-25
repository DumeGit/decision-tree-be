from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import xml.etree.ElementTree as ET
import zipfile
import os

app = Flask(__name__)
CORS(app)
entities = {}
links = {}  # Dictionary to store topic information
associations = {}  # List to store associations
UPLOAD_FOLDER = 'images'


@app.route("/get_children", methods=["GET"])
def get_children():
    try:
        node = request.args.get("node")
        children_list = [{"question": {'id': item[1], 'label': entities[item[1]].get('label')},
                          "answer": {'id': item[0], 'label': links[item[0]].get('label'),
                                     'image': links[item[0]].get('image')}} for item in
                         list(decision_tree.get(node, {}).items())]
        return jsonify(
            {"root": {'id': node, 'label': entities.get(node).get('label'), 'image': entities.get(node).get('image'), 'description': entities.get(node).get('description')},
             "children": children_list})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/images', methods=["GET"])
def get_image():
    filename = request.args.get("image")
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/load_triads", methods=["POST"])
def load_triads():
    try:
        uploaded_file = request.files["file"]
        if uploaded_file.filename != "":
            xml_file = extract_files(uploaded_file)
            entities, links = parse_xtm_file(xml_file)
            global decision_tree
            decision_tree = build_decision_tree(links)
            return jsonify(find_root_node(entities, links))
        else:
            return jsonify({"error": "No file uploaded."})
    except Exception as e:
        return jsonify({"error": str(e)})


def extract_files(file):
    with zipfile.ZipFile(file, 'r') as zip_ref:
        xml_files = [f for f in zip_ref.namelist() if f.endswith('.xml')]
        if not xml_files:
            return 'No XML file found in the zip'
        xml_filename = xml_files[0]
        zip_ref.extract(xml_filename)

        images_folder = 'images'
        os.makedirs(images_folder, exist_ok=True)

        for file_item in zip_ref.namelist():
            if file_item.endswith(('.png', '.jpg', '.jpeg')):
                zip_ref.extract(file_item, images_folder)

        return xml_filename


def parse_xtm_file(file_path):
    """
    Parses an XTM file and extracts relevant information.
    Assumes the XTM file follows the structure provided in your example.
    """
    tree = ET.parse(file_path)
    root = tree.getroot()

    for topic in root.findall(".//{http://www.topicmaps.org/xtm/1.0/}topic"):
        topic_id = topic.get("id")
        topic_type = topic.find(".//{http://www.topicmaps.org/xtm/1.0/}instanceOf").find(
            ".//{http://www.topicmaps.org/xtm/1.0/}subjectIndicatorRef").attrib[
            '{http://www.w3.org/1999/xlink}href'].split('#')[-1]
        base_name = topic.find(".//{http://www.topicmaps.org/xtm/1.0/}baseNameString").text
        image_name = ""
        description = ""
        if topic_type == 'linkingPhrase':
            links[topic_id] = {"label": base_name, "image": image_name, "description": description}
        else:
            occurence = topic.find(".//{http://www.topicmaps.org/xtm/1.0/}occurrence")
            if occurence is not None:
                file_path = occurence.find(".//{http://www.topicmaps.org/xtm/1.0/}resourceRef").attrib[
                    '{http://www.w3.org/1999/xlink}href']
                if file_path[0:4] == 'file':
                    image_name = file_path.split('/./')[1]
                else:
                    description = file_path
            entities[topic_id] = {"label": base_name, "image": image_name, "description" : description}

    for association in root.findall(".//{http://www.topicmaps.org/xtm/1.0/}association"):
        link_id = association.find(".//{http://www.topicmaps.org/xtm/1.0/}instanceOf").find(
            "{http://www.topicmaps.org/xtm/1.0/}topicRef").attrib['{http://www.w3.org/1999/xlink}href'].split('#')[-1]
        from_id = association.find(
            ".//{http://www.topicmaps.org/xtm/1.0/}member[1]/{http://www.topicmaps.org/xtm/1.0/}topicRef").attrib[
            '{http://www.w3.org/1999/xlink}href'].split('#')[-1]
        to_id = association.find(
            ".//{http://www.topicmaps.org/xtm/1.0/}member[2]/{http://www.topicmaps.org/xtm/1.0/}topicRef").attrib[
            '{http://www.w3.org/1999/xlink}href'].split('#')[-1]
        associations[link_id] = ({'from_id': from_id, 'to_id': to_id, 'label': links[link_id]["label"]})

    return entities, associations


def build_decision_tree(links):
    decision_tree = {}
    for id, data in links.items():
        if data.get('from_id') not in decision_tree:
            decision_tree[data.get('from_id')] = {}

        decision_tree[data.get('from_id')][id] = data.get('to_id')

    return decision_tree


def find_root_node(entities, links):
    target_nodes = set(data.get('to_id') for _, data in links.items())

    for entity_id, _ in entities.items():
        if entity_id not in target_nodes:
            children_list = [{"question": {'id': item[1], 'label': entities[item[1]].get('label'),
                                           'image': entities[item[1]].get('image')},
                              "answer": {'id': item[0], 'label': links[item[0]].get('label'),
                                         'image': entities[item[1]].get('image')}} for item in
                             list(decision_tree.get(entity_id, {}).items())]
            return {"root": {'id': entity_id, 'label': entities[entity_id].get('label'),
                             'image': entities[entity_id].get('image'), 'description': entities[entity_id].get('description')}, "children": children_list}

    return None


if __name__ == "__main__":
    app.run(debug=True)
