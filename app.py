import shutil

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import xml.etree.ElementTree as ET
import zipfile
import os

app = Flask(__name__)
CORS(app)
entities = {}
links = {}  # Dictionary to store topic information
associations = {}  # List to store associations
FOLDER_IGNORE_LIST = (".DS_Store", ".git", ".venv", "__pycache__", ".idea")


@app.route("/get_children", methods=["GET"])
def get_children():
    try:
        node = request.args.get("node")
        children_list = [{"question": {'id': item[1], 'label': entities[item[1]].get('label')},
                          "answer": {'id': item[0], 'label': links[item[0]].get('label'),
                                     'image': links[item[0]].get('image')}} for item in
                         list(decision_tree.get(node, {}).items())]
        return jsonify(
            {"root": {'id': node, 'label': entities.get(node).get('label'), 'image': entities.get(node).get('image'),
                      'description': entities.get(node).get('description')},
             "children": children_list})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/images', methods=["GET"])
def get_image():
    filename = request.args.get("image")
    return send_file(filename)


@app.route('/tree', methods=["GET"])
def start_tree():
    folder = request.args.get("name").strip()
    file = folder + ".xml"
    entities, links = parse_xtm_file(folder + '/' + file)
    global decision_tree
    decision_tree = build_decision_tree(links)
    return jsonify(find_root_node(entities, links))


@app.route('/trees', methods=["GET"])
def get_trees():
    folder_objects = []

    for item in os.listdir():
        if os.path.isdir(item) and item not in FOLDER_IGNORE_LIST:
            description = 'No description available'
            description_file_path = os.path.join(item, 'description.txt')
            # Check if the description.txt file exists in the directory
            if os.path.isfile(description_file_path):
                with open(description_file_path, 'r') as file:
                    description = file.read().strip()

            # Create a dictionary object representing the folder
            folder_object = {
                'name': item,
                'description': description
            }
            folder_objects.append(folder_object)
    return folder_objects


@app.route("/load_triads", methods=["POST"])
def load_triads():
    try:
        uploaded_file = request.files["file"]
        if uploaded_file.filename != "":
            xml_file = extract_files(uploaded_file)
            xml_file_folder = xml_file.split('.xml')[0]
            entities, links = parse_xtm_file(xml_file_folder + '/' + xml_file)
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
        txt_files = [f for f in zip_ref.namelist() if f.endswith('.txt')]

        if not xml_files and not txt_files:
            return 'No XML or TXT files found in the zip'

        xml_filename = xml_files[0] if xml_files else None

        folder_name = xml_filename.split('.xml')[0]

        if xml_filename:
            zip_ref.extract(xml_filename, folder_name)

        images_folder = folder_name + '/images'
        os.makedirs(images_folder, exist_ok=True)

        texts_folder = folder_name + '/texts'
        os.makedirs(texts_folder, exist_ok=True)

        for file_item in zip_ref.namelist():
            if file_item.endswith(('.png', '.jpg', '.jpeg', '.txt', '.htm')):
                if file_item.endswith(('.png', '.jpg', '.jpeg')):
                    extracted_path = zip_ref.extract(file_item, images_folder)
                    file_name = os.path.basename(file_item)
                    new_path = os.path.join(images_folder, file_name)
                elif file_item.endswith(('.txt', '.htm')):
                    extracted_path = zip_ref.extract(file_item, texts_folder)
                    file_name = os.path.basename(file_item)
                    new_path = os.path.join(texts_folder, file_name)
                shutil.move(extracted_path, new_path)
                intermediate_dir = os.path.dirname(extracted_path)
                while intermediate_dir and intermediate_dir != images_folder and intermediate_dir != texts_folder:
                    try:
                        os.rmdir(intermediate_dir)
                    except OSError:
                        break
                    intermediate_dir = os.path.dirname(intermediate_dir)

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
            for occurrence in topic.findall(".//{http://www.topicmaps.org/xtm/1.0/}occurrence"):
                if occurrence is not None:
                    file_path = occurrence.find(".//{http://www.topicmaps.org/xtm/1.0/}resourceRef").attrib[
                        '{http://www.w3.org/1999/xlink}href']
                    if file_path[0:4] == 'file':
                        _, file_extension = os.path.splitext(file_path)
                        if file_extension.lower() in ('.png', '.jpg', '.jpeg'):
                            split_path = file_path.split('/./')[1].split('/')
                            folder_name = split_path[0]
                            image_file = split_path[1]
                            image_name = folder_name + '/images/' + image_file
                        elif file_extension.lower() in ('.txt', '.htm'):
                            split_path = file_path.split('/./')[1].split('/')
                            folder_name = split_path[0]
                            text_file = split_path[1]
                            with open(folder_name + '/texts/' + text_file, 'r') as file:
                                description = file.read()

            entities[topic_id] = {"label": base_name, "image": image_name, "description": description}

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
                             'image': entities[entity_id].get('image'),
                             'description': entities[entity_id].get('description')}, "children": children_list}

    return None


if __name__ == "__main__":
    app.run(debug=True)
