import os
import shutil
import zipfile
from collections import deque

import patoolib
from lxml import etree
from functools import partial
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from PIL import Image
from werkzeug.exceptions import BadRequest, InternalServerError, NotFound, Conflict, HTTPException

app = Flask(__name__)
CORS(app)

FOLDER_IGNORE_LIST = {".DS_Store", ".git", ".venv", "__pycache__", ".idea", "venv"}


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return jsonify(error=str(e)), e.code
    return jsonify(error="An unexpected error occurred"), 500


@app.errorhandler(404)
def not_found(e):
    return jsonify(error="The requested resource was not found"), 404


@app.errorhandler(400)
def bad_request(e):
    return jsonify(error="Bad request"), 400


class Entity:
    def __init__(self, id, label, image="", description="", parent=None):
        self.id = id
        self.label = label
        self.image = image
        self.description = description
        self.parent = parent

    def to_dict(self):
        return {
            'id': self.id,
            'label': self.label,
            'image': self.image,
            'description': self.description,
            'parent': self.parent
        }


class Link:
    def __init__(self, id, label, image="", description=""):
        self.id = id
        self.label = label
        self.image = image
        self.description = description

    def to_dict(self):
        return {
            'id': self.id,
            'label': self.label,
            'image': self.image,
            'description': self.description
        }


class Association:
    def __init__(self, id, from_id, to_id, label):
        self.id = id
        self.from_id = from_id
        self.to_id = to_id
        self.label = label

    def to_dict(self):
        return {
            'id': self.id,
            'from_id': self.from_id,
            'to_id': self.to_id,
            'label': self.label
        }


class EntityStore:
    XTM_NS = "http://www.topicmaps.org/xtm/1.0/"
    XLINK_NS = "http://www.w3.org/1999/xlink"

    def __init__(self):
        self.entities = {}
        self.links = {}
        self.associations = {}
        self.decision_tree = {}

    def parse_xtm_file(self, file_path):
        parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.parse(file_path, parser)
        root = tree.getroot()

        nsmap = {'xtm': self.XTM_NS, 'xlink': self.XLINK_NS}
        find = partial(root.find, namespaces=nsmap)
        findall = partial(root.findall, namespaces=nsmap)

        for topic in findall('.//xtm:topic'):
            self._parse_topic(topic, nsmap)

        for association in findall('.//xtm:association'):
            self._parse_association(association, nsmap)

    def _parse_topic(self, topic, nsmap):
        topic_id = topic.get("id")
        instance_of = topic.find('.//xtm:instanceOf', namespaces=nsmap)
        topic_type = 'linkingPhrase' if instance_of is not None and \
                                        instance_of.find('.//xtm:subjectIndicatorRef', namespaces=nsmap).get(
                                            f'{{{self.XLINK_NS}}}href').endswith('#linkingPhrase') \
            else 'topic'

        base_name = topic.findtext('.//xtm:baseNameString', namespaces=nsmap)
        image_name, description = "", ""

        if topic_type == 'linkingPhrase':
            self.links[topic_id] = Link(topic_id, base_name, image_name, description)
        else:
            for occurrence in topic.findall('.//xtm:occurrence', namespaces=nsmap):
                resource_ref = occurrence.find('.//xtm:resourceRef', namespaces=nsmap)
                if resource_ref is not None:
                    file_path = resource_ref.get(f'{{{self.XLINK_NS}}}href')
                    if file_path.startswith('file'):
                        image_name, description = self._parse_occurrence(file_path, image_name, description)

            self.entities[topic_id] = Entity(topic_id, base_name, image_name, description)

    def _parse_occurrence(self, file_path, image_name, description):
        _, file_extension = os.path.splitext(file_path)
        folder_name, file_name = file_path.split('/./')[1].split('/')
        if file_extension.lower() in ('.png', '.jpg', '.jpeg', '.svg'):
            image_name = os.path.join(folder_name, 'images', file_name)
        elif file_extension.lower() in ('.txt'):
            with open(os.path.join(folder_name, 'texts', file_name), 'r') as file:
                description = file.read()
        elif file_extension.lower() in ('.htm', '.html'):
            file_name_folder = os.path.join(folder_name, 'texts', file_name)
            if os.path.isfile(file_name_folder):
                with open(os.path.join(folder_name, 'texts', file_name), 'r') as file:
                    description = file.read()
            else:
                with open(os.path.join(folder_name, 'texts', file_name + 'l'), 'r') as file:
                    description = file.read()
        return image_name, description

    def _parse_association(self, association, nsmap):
        link_id = \
            association.find('.//xtm:instanceOf/xtm:topicRef', namespaces=nsmap).get(f'{{{self.XLINK_NS}}}href').split(
                '#')[
                -1]
        members = association.findall('.//xtm:member/xtm:topicRef', namespaces=nsmap)
        from_id = members[0].get(f'{{{self.XLINK_NS}}}href').split('#')[-1]
        to_id = members[1].get(f'{{{self.XLINK_NS}}}href').split('#')[-1]

        self.associations[link_id] = Association(link_id, from_id, to_id, self.links[link_id].label)

    def build_decision_tree(self):
        self.decision_tree = {}
        for assoc in self.associations.values():
            if assoc.from_id not in self.decision_tree:
                self.decision_tree[assoc.from_id] = {}
            self.decision_tree[assoc.from_id][assoc.id] = assoc.to_id

        visited = set()

        def check_circular(node_id, path):
            if node_id in path:
                raise ValueError(f"Circular reference detected: {' -> '.join(path + [node_id])}")
            if node_id in visited:
                return
            visited.add(node_id)
            path.append(node_id)
            for child_id in self.decision_tree.get(node_id, {}).values():
                check_circular(child_id, path)
            path.pop()

        root = self.find_root_node()
        if root:
            check_circular(root['root']['id'], [])
        else:
            raise ValueError("No root node found in the decision tree")

        for parent_id, children in self.decision_tree.items():
            for child_id in children.values():
                self.entities[child_id].parent = parent_id

    def find_root_node(self):
        target_nodes = {assoc.to_id for assoc in self.associations.values()}
        for entity_id in self.entities:
            if entity_id not in target_nodes:
                return create_node(entity_id)
        return None

    def clear_tree(self):
        self.entities.clear()
        self.links.clear()
        self.associations.clear()
        self.decision_tree.clear()


entity_store = EntityStore()


@app.route("/api/get_children", methods=["GET"])
def get_children():
    try:
        node_id = request.args.get("node")
        if not node_id:
            raise BadRequest("Missing 'node' parameter")

        node = create_node(node_id)
        if not node:
            raise NotFound(f"Node with id '{node_id}' not found")

        return jsonify(node)
    except Exception as e:
        app.logger.error(f"Error in get_children: {str(e)}")
        raise InternalServerError("An unexpected error occurred")


@app.route('/api/images', methods=["GET"])
def get_image():
    try:
        filename = request.args.get("image")
        if not filename:
            raise BadRequest("Missing 'image' parameter")

        if not os.path.exists(filename):
            raise NotFound(f"Image '{filename}' not found")

        return send_file(filename)
    except Exception as e:
        app.logger.error(f"Error in get_image: {str(e)}")
        raise InternalServerError("An unexpected error occurred")


@app.route('/api/tree', methods=["GET"])
def start_tree():
    try:
        folder = request.args.get("name")
        if not folder:
            raise BadRequest("Missing 'name' parameter")

        folder = folder.strip()
        file = f"{folder}.xml"

        if not os.path.exists(os.path.join(folder, file)):
            raise NotFound(f"Tree file '{file}' not found in folder '{folder}'")

        entity_store.clear_tree()
        entity_store.parse_xtm_file(os.path.join(folder, file))
        entity_store.build_decision_tree()

        root_node = entity_store.find_root_node()
        if not root_node:
            raise NotFound("No root node found in the parsed tree")

        return jsonify(root_node)
    except Exception as e:
        app.logger.error(f"Error in start_tree: {str(e)}")
        raise InternalServerError("An unexpected error occurred")


@app.route('/api/tree/delete', methods=["DELETE"])
def delete_tree():
    try:
        folder = request.args.get("name")
        if not folder:
            raise BadRequest("Missing 'name' parameter")

        folder = folder.strip()
        if not os.path.exists(folder):
            raise NotFound(f"Folder '{folder}' not found")

        shutil.rmtree(folder)
        return jsonify({"message": f"Tree '{folder}' has been deleted"})
    except Exception as e:
        app.logger.error(f"Error in delete_tree: {str(e)}")
        raise InternalServerError("An unexpected error occurred")


@app.route('/api/trees', methods=["GET"])
def get_trees():
    try:
        folder_objects = []
        for item in os.listdir():
            if os.path.isdir(item) and item not in FOLDER_IGNORE_LIST:
                description = 'No description available'
                description_file_path = os.path.join(item, 'description.txt')
                if os.path.isfile(description_file_path):
                    with open(description_file_path, 'r') as file:
                        description = file.read().strip()
                folder_objects.append({'name': item, 'description': description})
        return jsonify(folder_objects)
    except Exception as e:
        app.logger.error(f"Error in get_trees: {str(e)}")
        raise InternalServerError("An unexpected error occurred")


@app.route("/api/load_tree", methods=["POST"])
def load_tree():
    try:
        if 'file' not in request.files:
            raise BadRequest("No file part in the request")

        uploaded_file = request.files["file"]
        if not uploaded_file.filename:
            raise BadRequest("No file selected")

        # Extract the tree name from the uploaded file
        tree_name = os.path.splitext(uploaded_file.filename)[0]

        # Check if a tree with this name already exists
        if tree_exists(tree_name):
            raise Conflict(
                f"A tree with the name '{tree_name}' already exists. Please choose a different name or delete the existing tree first.")

        entity_store.clear_tree()
        xml_file, xml_file_folder = extract_files(uploaded_file)
        entity_store.parse_xtm_file(os.path.join(xml_file_folder, xml_file))
        entity_store.build_decision_tree()

        root_node = entity_store.find_root_node()
        if not root_node:
            raise NotFound("No root node found in the uploaded tree")

        return jsonify(root_node)
    except Exception as e:
        app.logger.error(f"Error in load_triads: {str(e)}")
        if isinstance(e, (BadRequest, NotFound, Conflict)):
            raise
        raise InternalServerError("An unexpected error occurred")


@app.route("/api/test", methods=["GET"])
def test():
    return jsonify({"message": "Hello World!"})


@app.route("/api/tree_ascii", methods=["GET"])
def get_tree_ascii():
    try:
        root_node = entity_store.find_root_node()
        if not root_node:
            raise NotFound("No tree found")

        tree_ascii = generate_tree_ascii(root_node)
        return jsonify({"tree_ascii": tree_ascii})
    except Exception as e:
        app.logger.error(f"Error in get_tree_ascii: {str(e)}")
        raise InternalServerError("An unexpected error occurred")


@app.route("/api/tree_graph", methods=["GET"])
def get_tree_graph():
    try:
        path = request.args.get("name")
        if not path:
            raise BadRequest("Missing 'name' parameter")

        folder, filename = path.split('/')
        matching_files = [file for file in os.listdir(folder) if file.startswith(filename)]

        if not matching_files:
            raise NotFound(f"No matching files found for '{filename}' in folder '{folder}'")

        return send_file(os.path.join(folder, matching_files[0]))
    except Exception as e:
        app.logger.error(f"Error in get_tree_graph: {str(e)}")
        raise InternalServerError("An unexpected error occurred")


@app.route("/api/get_path", methods=["GET"])
def get_paths():
    try:
        node_id = request.args.get("node")
        if not node_id:
            raise BadRequest("Missing 'node' parameter")

        paths = find_paths_to_node(node_id)
        if not paths:
            raise NotFound(f"No paths found to node with id '{node_id}'")
        paths.reverse()
        return jsonify(paths)
    except Exception as e:
        app.logger.error(f"Error in get_paths: {str(e)}")
        raise InternalServerError("An unexpected error occurred")


def generate_tree_ascii(node, visited=None, node_ids=None, prefix="", is_last=True):
    if visited is None:
        visited = set()
    if node_ids is None:
        node_ids = {}

    tree_ascii = prefix
    if is_last:
        tree_ascii += "└── "
        prefix += "    "
    else:
        tree_ascii += "├── "
        prefix += "│   "

    node_id = node["root"]["id"]
    if node_id not in node_ids:
        node_ids[node_id] = len(node_ids) + 1

    tree_ascii += f"[{node_ids[node_id]}] {node['root']['label']} [{node_id}]\n"

    if node_id in visited:
        return tree_ascii

    visited.add(node_id)

    children = node["children"]
    for i, child in enumerate(children):
        is_last_child = i == len(children) - 1
        child_node = create_node(child["question"]["id"])
        child_id = child_node["root"]["id"]

        if child_id in visited:
            tree_ascii += prefix + (
                "└── " if is_last_child else "├── ") + f"[{node_ids[child_id]}] {child_node['root']['label']} [{child_id}]\n"
        else:
            tree_ascii += generate_tree_ascii(child_node, visited, node_ids, prefix, is_last_child)

    return tree_ascii


def extract_files(file):
    file_extension = os.path.splitext(file.filename)[1].lower()

    if file_extension == '.zip':
        with zipfile.ZipFile(file, 'r') as zip_ref:
            return _extract_from_zip(zip_ref)
    elif file_extension == '.rar':
        return _extract_from_rar(file)
    else:
        raise BadRequest('Unsupported file type. Only ZIP and RAR are supported.')


def _extract_from_zip(zip_ref):
    xml_files = [f for f in zip_ref.namelist() if f.endswith('.xml')]
    description_file = next((f for f in zip_ref.namelist() if f.endswith('description.txt')), None)

    if not xml_files:
        raise BadRequest('No XML files found in the zip')

    xml_filename = xml_files[0]
    folder_name = xml_filename.split('.')[0]

    if tree_exists(folder_name):
        raise Conflict(
            f"A tree with the name '{folder_name}' already exists. Please choose a different name or delete the existing tree first.")

    zip_ref.extract(xml_filename, folder_name)
    if description_file:
        zip_ref.extract(description_file, folder_name)

    images_folder = os.path.join(folder_name, 'images')
    texts_folder = os.path.join(folder_name, 'texts')
    os.makedirs(images_folder, exist_ok=True)
    os.makedirs(texts_folder, exist_ok=True)

    for file_item in zip_ref.namelist():
        if file_item.startswith('tree_graph'):
            zip_ref.extract(file_item, folder_name)
        elif file_item.endswith(('.png', '.jpg', '.jpeg')):
            extracted_path = zip_ref.extract(file_item)

            img = Image.open(extracted_path)

            quality = 80

            new_path = os.path.join(images_folder, os.path.basename(file_item))
            img.save(new_path, optimize=True, quality=quality)

            os.remove(extracted_path)
        elif file_item.endswith('.svg'):
            extracted_path = zip_ref.extract(file_item)
            new_path = os.path.join(images_folder, os.path.basename(file_item))
            shutil.move(extracted_path, new_path)
        else:
            extracted_path = zip_ref.extract(file_item, texts_folder if file_item.endswith(
                ('.txt', '.htm', '.html')) else images_folder)
            new_path = os.path.join(
                texts_folder if file_item.endswith(('.txt', '.htm', '.html')) else images_folder,
                os.path.basename(file_item))
            shutil.move(extracted_path, new_path)
            clean_up_empty_directories(os.path.dirname(extracted_path), images_folder, texts_folder)

    return xml_filename, folder_name


def _extract_from_rar(file):
    temp_dir = "temp_extracted"
    os.makedirs(temp_dir, exist_ok=True)

    temp_file_path = os.path.join(temp_dir, file.filename)
    file.save(temp_file_path)

    patoolib.extract_archive(temp_file_path, outdir=temp_dir)

    extracted_files = []
    for root, _, files in os.walk(temp_dir):
        extracted_files.extend([os.path.join(root, f) for f in files])

    xml_files = [f for f in extracted_files if f.endswith('.xml')]
    description_file = next((f for f in extracted_files if f.endswith('description.txt')), None)

    if not xml_files:
        raise BadRequest('No XML files found in the RAR')

    xml_filename = os.path.basename(xml_files[0])
    folder_name = os.path.splitext(xml_filename)[0]

    if tree_exists(folder_name):
        raise Conflict(
            f"A tree with the name '{folder_name}' already exists. Please choose a different name or delete the existing tree first.")

    os.makedirs(folder_name, exist_ok=True)

    shutil.copy(xml_files[0], folder_name)
    if description_file:
        shutil.copy(description_file, folder_name)

    images_folder = os.path.join(folder_name, 'images')
    texts_folder = os.path.join(folder_name, 'texts')
    os.makedirs(images_folder, exist_ok=True)
    os.makedirs(texts_folder, exist_ok=True)

    for file_item in extracted_files:
        if file_item == 'description.txt':
            continue
        if file_item.startswith('tree_graph'):
            shutil.move(file_item, folder_name)
        elif file_item.endswith(('.png', '.jpg', '.jpeg')):
            img = Image.open(file_item)
            quality = 80
            new_path = os.path.join(images_folder, os.path.basename(file_item))
            img.save(new_path, optimize=True, quality=quality)
            os.remove(file_item)
        elif file_item.endswith('.svg'):
            new_path = os.path.join(images_folder, os.path.basename(file_item))
            shutil.copy(file_item, new_path)
        elif file_item.endswith(('.txt', '.htm', '.html')):
            new_path = os.path.join(
                texts_folder if file_item.endswith(('.txt', '.htm', '.html')) else images_folder,
                os.path.basename(file_item))
            shutil.copy(file_item, new_path)
            clean_up_empty_directories(os.path.dirname(file_item), images_folder, texts_folder)

    shutil.rmtree(temp_dir)

    return xml_filename, folder_name


def tree_exists(tree_name):
    return os.path.exists(tree_name) and os.path.isdir(tree_name)


def clean_up_empty_directories(intermediate_dir, images_folder, texts_folder):
    while intermediate_dir and intermediate_dir not in {images_folder, texts_folder}:
        try:
            os.rmdir(intermediate_dir)
        except OSError:
            break
        intermediate_dir = os.path.dirname(intermediate_dir)


def create_node(node_id):
    children_list = [
        {
            "question": entity_store.entities[item[1]].to_dict(),
            "answer": entity_store.links[item[0]].to_dict()
        }
        for item in list(entity_store.decision_tree.get(node_id, {}).items())
    ]
    node = entity_store.entities.get(node_id)
    return {"root": node.to_dict(), "children": children_list}


def find_paths_to_node(target_id):
    def build_parent_map():
        parent_map = {}
        for parent_id, children in entity_store.decision_tree.items():
            for _, child_id in children.items():
                if child_id not in parent_map:
                    parent_map[child_id] = []
                parent_map[child_id].append(parent_id)
        return parent_map

    def bfs():
        parent_map = build_parent_map()
        queue = deque([(target_id, [])])
        paths = []

        while queue:
            current_id, path = queue.popleft()
            current_node = entity_store.entities[current_id].to_dict()
            current_path = [current_node] + path

            if current_id not in parent_map:
                paths.append(current_path)
            else:
                for parent_id in parent_map[current_id]:
                    queue.append((parent_id, current_path))

        return paths

    return bfs()


if __name__ == "__main__":
    app.run(debug=True)
