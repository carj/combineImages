import glob
import os
import shutil
from time import sleep

import natsort
from natsort import ns
from pyPreservica import *
from multiprocessing import Pool
from PIL import Image
from xml.etree.ElementTree import Element, SubElement, ElementTree
import csv
from tinydb import TinyDB, Query


class DC:
    def __init__(self, csv_row: list):
        self.contributor: str = csv_row[1]
        self.coverage: str = csv_row[2]
        self.creator: str = csv_row[3]
        self.date: str = csv_row[4]
        self.description: str = csv_row[5]
        self.dc_format: str = csv_row[6]
        self.identifier: str = csv_row[7]
        self.language: str = csv_row[8]
        self.obj_title: str = csv_row[9]
        self.publisher: str = csv_row[10]
        self.rights: str = csv_row[11]
        self.source: str = csv_row[12]
        self.subject: str = csv_row[13]
        self.title: str = csv_row[14]
        self.type_dc: str = csv_row[15]


def download_asset(asset: Asset, client, folder_name):
    for representation in client.representations(asset):
        if representation.rep_type == "Preservation":
            for content_object in client.content_objects(representation):
                for generation in client.generations(content_object):
                    if generation.active:
                        for bitstream in generation.bitstreams:
                            bs: Bitstream = bitstream
                            path: str = os.path.join(f"./{folder_name}", bitstream.filename)
                            if os.path.exists(path) is False:
                                client.bitstream_content(bitstream, path)
                                if bs.fixity['SHA1'] != sha1(path):
                                    os.remove(path)
                                    download_asset(asset, client, folder_name)
                            else:
                                if bs.fixity['SHA1'] != sha1(path):
                                    os.remove(path)
                                    download_asset(asset, client, folder_name)


def main(client: EntityAPI, record_folder: Folder, dublin_core_data: DC, security_tag: str):
    security_tag = record_folder.security_tag

    folder_name: str = record_folder.title

    workflow_size: int = len(list(workflow.workflow_instances(workflow_state="Active", workflow_type="Ingest")))
    while workflow_size > 12:
        print(f"{workflow_size} Active ingests running. Waiting for ingest queue to go down...")
        sleep(120)
        workflow_size: int = len(list(workflow.workflow_instances(workflow_state="Active", workflow_type="Ingest")))

    if os.path.isdir(folder_name) is False:
        os.mkdir(folder_name)

    pool = Pool(processes=POOL_SIZE)

    for asset in filter(only_assets, client.descendants(folder=record_folder)):
        pool.apply_async(func=download_asset, args=(asset, client, folder_name))

    pool.close()
    pool.join()

    tiff_images = glob.glob(os.path.join(f"./{folder_name}", "*.tif"))
    sorted_tiffs: list = natsort.natsorted(seq=tiff_images, alg=ns.PATH)

    num_tiff_image: int = len(sorted_tiffs)

    fields: dict = {"xip.parent_ref": record_folder.reference, "xip.document_type": "IO"}
    items: int = search.search_index_filter_hits(query="tif", filter_values=fields)

    assert items == num_tiff_image

    images = []

    dc_tree = xml.etree.ElementTree.parse('dc.xml')
    dc_root = dc_tree.getroot()

    source = dc_root.find("{http://purl.org/dc/elements/1.1/}source")

    dc_root.find("{http://purl.org/dc/elements/1.1/}title").text = dublin_core_data.title
    dc_root.find("{http://purl.org/dc/elements/1.1/}creator").text = dublin_core_data.creator
    dc_root.find("{http://purl.org/dc/elements/1.1/}subject").text = dublin_core_data.subject
    dc_root.find("{http://purl.org/dc/elements/1.1/}description").text = dublin_core_data.description

    dc_root.find("{http://purl.org/dc/elements/1.1/}publisher").text = dublin_core_data.publisher
    dc_root.find("{http://purl.org/dc/elements/1.1/}contributor").text = dublin_core_data.contributor
    dc_root.find("{http://purl.org/dc/elements/1.1/}date").text = dublin_core_data.date
    dc_root.find("{http://purl.org/dc/elements/1.1/}type").text = dublin_core_data.type_dc

    dc_root.find("{http://purl.org/dc/elements/1.1/}format").text = dublin_core_data.dc_format
    dc_root.find("{http://purl.org/dc/elements/1.1/}identifier").text = dublin_core_data.identifier
    dc_root.find("{http://purl.org/dc/elements/1.1/}language").text = dublin_core_data.language
    dc_root.find("{http://purl.org/dc/elements/1.1/}coverage").text = dublin_core_data.coverage
    dc_root.find("{http://purl.org/dc/elements/1.1/}rights").text = dublin_core_data.rights

    for tiff in sorted_tiffs:
        i = Image.open(f"./{tiff}")
        images.append(i)

    pdf_path = os.path.join(f"./{folder_name}", "output.pdf")

    dc_tree.write(open(os.path.join(f"./{folder_name}", 'dublin.xml'), mode='wb'), encoding='utf-8')

    images[0].save(
        pdf_path, "PDF", resolution=100.0, save_all=True, append_images=images[1:]
    )

    asset_metadata = {"http://www.openarchives.org/OAI/2.0/oai_dc/": os.path.join(f"./{folder_name}", 'dublin.xml')}

    identifiers = {"identifier": dublin_core_data.title}

    package = complex_asset_package(parent_folder=parent, preservation_files_list=sorted_tiffs,
                                    access_files_list=[pdf_path], SecurityTag=security_tag,
                                    Title=dublin_core_data.title, CustomType="Civil Case",
                                    Description=dublin_core_data.subject,
                                    Asset_Metadata=asset_metadata, Identifiers=identifiers)

    upload.upload_zip_package(path_to_zip_package=package, folder=parent, delete_after_upload=True,
                              callback=UploadProgressConsoleCallback(package))

    shutil.rmtree(folder_name)


if __name__ == '__main__':
    client = EntityAPI()
    upload = UploadAPI()
    search = ContentAPI()
    workflow = WorkflowAPI()

    print(client)

    config = configparser.ConfigParser()
    config.read('credentials.properties')

    source_material_folder = config['credentials']['source_folder']
    source = client.folder(source_material_folder)
    print(f"Looking for Content in {client.folder(source.parent).title} / {source.title}")

    security_tag = config['credentials']['security.tag']

    parent_folder = config['credentials']['target_folder']
    parent = client.folder(parent_folder)
    print(f"Ingesting new Content in {client.folder(parent.parent).title}  / {parent.title}")

    csv_file = config['credentials']['csv_file']
    assert os.path.isfile(csv_file) is True
    print(f"Found CSV file containing records: {csv_file}")

    POOL_SIZE = 6

    db_name = os.path.basename(csv_file).replace(".csv", ".json")

    db = TinyDB(db_name)


    sha1 = FileHash(hashlib.sha1)

    error_back_off: int = 30

    while True:

        db_missing = TinyDB(f'{os.path.basename(csv_file).replace(".csv", "")}-missing.json')
        db_missing.truncate()

        spreadsheet_rows: int = 0

        try:
            with open(f'{csv_file}', newline='') as csvfile:
                reader = csv.reader(csvfile, delimiter=',', quotechar='|')
                reader.__next__()
                for row in reader:
                    spreadsheet_rows = spreadsheet_rows + 1
                    dublin_core_data = DC(row)

                    ## look up Title in db.json
                    db_record = Query()
                    db_results = db.search(db_record.title == dublin_core_data.title)
                    if len(db_results) > 0:
                        rec = db_results[0]
                        print(f"Found Existing Record {rec['title']} in Preservica. Skipping...")
                        continue

                    # lookup object in Preservica
                    preservica_records = client.identifier('identifier', dublin_core_data.title)
                    if len(preservica_records) > 0:
                        e: Entity = preservica_records.pop()
                        db.insert({'title': dublin_core_data.title, 'reference': e.reference})
                        print(f"Found Existing Record {e.title} in Preservica. Skipping...")
                        continue

                    title = dublin_core_data.title
                    metadata_fields = {"xip.parent_hierarchy": source_material_folder, "xip.document_type": "SO",
                                       "xip.title": f'{title}'}
                    hits = list(search.search_index_filter_list(query="%", filter_values=metadata_fields))
                    if len(hits) == 1:
                        print(f"Processing Item: {title}")
                        record_folder = client.folder(hits[0]['xip.reference'])
                        main(client, record_folder, dublin_core_data, security_tag)
                    if len(hits) == 0:
                        print(f"Could Not Find Item for {title}")
                        db_missing.insert({'title': dublin_core_data.title, 'subject': dublin_core_data.subject})
                    if len(hits) > 1:
                        for h in hits:
                            record_folder = client.folder(h['xip.reference'])
                            print(f"Processing Item: {record_folder.title}")
                            dublin_core_data.title = record_folder.title
                            db_results = db.search(db_record.title == dublin_core_data.title)
                            if len(db_results) > 0:
                                rec = db_results[0]
                                print(f"Found Existing Record {rec['title']} in Preservica. Skipping...")
                                continue
                            preservica_records = client.identifier('identifier', dublin_core_data.title)
                            if len(preservica_records) > 0:
                                e: Entity = preservica_records.pop()
                                db.insert({'title': dublin_core_data.title, 'reference': e.reference})
                                print(f"Found Existing Record {e.title} in Preservica. Skipping...")
                                continue
                            main(client, record_folder, dublin_core_data, security_tag)

            print(f"Completed Ingests")
            print(f"Re-start the script again to find any missing ingests")
            print(f"Confirmed ingested {len(db)}")
            print(f"Items in spreadsheet but no data found ingested {len(db_missing)}")
            print(f"Rows in spreadsheet {spreadsheet_rows}")
            exit(1)

        except Exception as e:
            print(f"Network Error.  Re-trying in {error_back_off} secs....")
            sleep(error_back_off)
            error_back_off = error_back_off * 2
            if error_back_off > 60 * 60:
                print(f"Could Not Resolve Network Error. Exiting.")
                print(e)
                exit(1)
