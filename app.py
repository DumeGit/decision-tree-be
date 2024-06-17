import os
import shutil
import zipfile
import xml.etree.ElementTree as ET
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from PIL import Image

app = Flask(__name__)
CORS(app)

FOLDER_IGNORE_LIST = {".DS_Store", ".git", ".venv", "__pycache__", ".idea", "venv"}


class Entity:
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
    def __init__(self):
        self.entities = {}
        self.links = {}
        self.associations = {}
        self.decision_tree = {}

    def parse_xtm_file(self, file_path):
        tree = ET.parse(file_path)
        root = tree.getroot()

        for topic in root.findall(".//{http://www.topicmaps.org/xtm/1.0/}topic"):
            self._parse_topic(topic)
        for association in root.findall(".//{http://www.topicmaps.org/xtm/1.0/}association"):
            self._parse_association(association)

    def _parse_topic(self, topic):
        topic_id = topic.get("id")
        topic_type = topic.find(".//{http://www.topicmaps.org/xtm/1.0/}instanceOf") \
            .find(".//{http://www.topicmaps.org/xtm/1.0/}subjectIndicatorRef") \
            .attrib['{http://www.w3.org/1999/xlink}href'].split('#')[-1]
        base_name = topic.find(".//{http://www.topicmaps.org/xtm/1.0/}baseNameString").text
        image_name, description = "", ""

        if topic_type == 'linkingPhrase':
            self.links[topic_id] = Link(topic_id, base_name, image_name, description)
        else:
            for occurrence in topic.findall(".//{http://www.topicmaps.org/xtm/1.0/}occurrence"):
                file_path = occurrence.find(".//{http://www.topicmaps.org/xtm/1.0/}resourceRef") \
                    .attrib['{http://www.w3.org/1999/xlink}href']
                if file_path.startswith('file'):
                    _, file_extension = os.path.splitext(file_path)
                    folder_name, file_name = file_path.split('/./')[1].split('/')
                    if file_extension.lower() in ('.png', '.jpg', '.jpeg'):
                        image_name = os.path.join(folder_name, 'images', file_name)
                    elif file_extension.lower() in ('.txt', '.htm'):
                        with open(os.path.join(folder_name, 'texts', file_name), 'r') as file:
                            description = file.read()
            self.entities[topic_id] = Entity(topic_id, base_name, image_name, description)

    def _parse_occurrence(self, file_path):
        _, file_extension = os.path.splitext(file_path)
        folder_name, file_name = file_path.split('/./')[1].split('/')
        image_name = ""
        text = ""
        if file_extension.lower() in ('.png', '.jpg', '.jpeg'):
            image_name = os.path.join(folder_name, 'images', file_name)
        elif file_extension.lower() in ('.txt', '.htm'):
            with open(os.path.join(folder_name, 'texts', file_name), 'r') as file:
                text = file.read()
        return image_name, text

    def _parse_association(self, association):
        link_id = association.find(".//{http://www.topicmaps.org/xtm/1.0/}instanceOf") \
            .find("{http://www.topicmaps.org/xtm/1.0/}topicRef") \
            .attrib['{http://www.w3.org/1999/xlink}href'].split('#')[-1]
        from_id = \
        association.find(".//{http://www.topicmaps.org/xtm/1.0/}member[1]/{http://www.topicmaps.org/xtm/1.0/}topicRef") \
            .attrib['{http://www.w3.org/1999/xlink}href'].split('#')[-1]
        to_id = \
        association.find(".//{http://www.topicmaps.org/xtm/1.0/}member[2]/{http://www.topicmaps.org/xtm/1.0/}topicRef") \
            .attrib['{http://www.w3.org/1999/xlink}href'].split('#')[-1]
        self.associations[link_id] = Association(link_id, from_id, to_id, self.links[link_id].label)

    def build_decision_tree(self):
        for assoc in self.associations.values():
            if assoc.from_id not in self.decision_tree:
                self.decision_tree[assoc.from_id] = {}
            self.decision_tree[assoc.from_id][assoc.id] = assoc.to_id

    def find_root_node(self):
        target_nodes = {assoc.to_id for assoc in self.associations.values()}
        for entity_id in self.entities:
            if entity_id not in target_nodes:
                children_list = [
                    {
                        "question": self.entities[item[1]].to_dict(),
                        "answer": self.links[item[0]].to_dict()
                    }
                    for item in list(self.decision_tree.get(entity_id, {}).items())
                ]
                return {
                    "root": self.entities[entity_id].to_dict(),
                    "children": children_list
                }
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
        node = request.args.get("node")
        children_list = [
            {
                "question": entity_store.entities[item[1]].to_dict(),
                "answer": entity_store.links[item[0]].to_dict()
            }
            for item in list(entity_store.decision_tree.get(node, {}).items())
        ]
        return jsonify({
            "root": entity_store.entities.get(node).to_dict(),
            "children": children_list
        })
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/images', methods=["GET"])
def get_image():
    filename = request.args.get("image")
    return send_file(filename)


@app.route('/api/tree', methods=["GET"])
def start_tree():
    entity_store.clear_tree()
    folder = request.args.get("name").strip()
    file = f"{folder}.xml"
    entity_store.parse_xtm_file(os.path.join(folder, file))
    entity_store.build_decision_tree()
    return jsonify(entity_store.find_root_node())


@app.route('/api/tree/delete', methods=["DELETE"])
def delete_tree():
    folder = request.args.get("name").strip()
    shutil.rmtree(folder)
    return jsonify({"message": "Tree has been deleted"})


@app.route('/api/trees', methods=["GET"])
def get_trees():
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


@app.route("/api/load_triads", methods=["POST"])
def load_triads():
    try:
        uploaded_file = request.files["file"]
        if uploaded_file.filename:
            entity_store.clear_tree()
            xml_file = extract_files(uploaded_file)
            xml_file_folder = xml_file.split('.xml')[0]
            entity_store.parse_xtm_file(os.path.join(xml_file_folder, xml_file))
            entity_store.build_decision_tree()
            return jsonify(entity_store.find_root_node())
        else:
            return jsonify({"error": "No file uploaded."})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/test", methods=["GET"])
def test():
    return jsonify({"message": "Hello World!"})


def extract_files(file):
    with zipfile.ZipFile(file, 'r') as zip_ref:
        xml_files = [f for f in zip_ref.namelist() if f.endswith('.xml')]
        description_file = next((f for f in zip_ref.namelist() if f.endswith('description.txt')), None)

        if not xml_files:
            return 'No XML files found in the zip'

        xml_filename = xml_files[0]
        folder_name = xml_filename.split('.')[0]

        zip_ref.extract(xml_filename, folder_name)
        if description_file:
            zip_ref.extract(description_file, folder_name)

        images_folder = os.path.join(folder_name, 'images')
        texts_folder = os.path.join(folder_name, 'texts')
        os.makedirs(images_folder, exist_ok=True)
        os.makedirs(texts_folder, exist_ok=True)

        for file_item in zip_ref.namelist():
            if file_item.endswith(('.png', '.jpg', '.jpeg')):
                extracted_path = zip_ref.extract(file_item)

                # Open the image for compression
                img = Image.open(extracted_path)

                # Adjust quality (lower value means higher compression)
                quality = 80

                # Save the compressed image to a new path
                new_path = os.path.join(images_folder, os.path.basename(file_item))
                img.save(new_path, optimize=True, quality=quality)

                # Clean up the temporary extracted file
                os.remove(extracted_path)
            else:
                extracted_path = zip_ref.extract(file_item, texts_folder if file_item.endswith(
                    ('.txt', '.htm')) else images_folder)
                new_path = os.path.join(
                    texts_folder if file_item.endswith(('.txt', '.htm')) else images_folder,
                    os.path.basename(file_item))
                shutil.move(extracted_path, new_path)
                clean_up_empty_directories(os.path.dirname(extracted_path), images_folder, texts_folder)

        return xml_filename


def clean_up_empty_directories(intermediate_dir, images_folder, texts_folder):
    while intermediate_dir and intermediate_dir not in {images_folder, texts_folder}:
        try:
            os.rmdir(intermediate_dir)
        except OSError:
            break
        intermediate_dir = os.path.dirname(intermediate_dir)


if __name__ == "__main__":
    app.run(debug=True)
