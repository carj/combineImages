import itertools
import csv
from natsort import natsort
from pyPreservica import *

if __name__ == '__main__':
    client = EntityAPI()
    search = ContentAPI()

    config = configparser.ConfigParser()
    config.read('credentials.properties')

    csv_file = config['credentials']['csv_file']
    csv_file_audit = csv_file.replace(".csv", "-audit.csv")

    source_material_folder = config['credentials']['source_folder']
    source_folder = client.folder(source_material_folder)

    parent_folder = config['credentials']['target_folder']
    parent = client.folder(parent_folder)
    print(f"Auditing new Content in {client.folder(parent.parent).title}  / {parent.title} Compared with"
          f" {client.folder(source_folder.parent).title}  / {source_folder.title}")

    metadata_fields = {"xip.parent_ref": source_material_folder, "xip.document_type": "SO", 'xip.title': '*'}
    source_list = list(search.search_index_filter_list(query="%", page_size=250, filter_values=metadata_fields,
                                                       sort_values={'xip.title': 'asc'}))
    source_map = {}
    source: list = []
    for x in source_list:
        source.append(x['xip.title'])
        source_map[x['xip.title']] = f"https://us.preservica.com/explorer/explorer.html#properties:SO&{x['xip.reference']}"

    metadata_fields = {"xip.parent_ref": parent_folder, "xip.document_type": "IO", 'xip.title': '*'}
    target_list = list(search.search_index_filter_list(query="%", page_size=250, filter_values=metadata_fields,
                                                       sort_values={'xip.title': 'asc'}))
    target_map = {}
    target: list = []
    for x in target_list:
        target.append(x['xip.title'])
        target_map[x['xip.title']] = f"https://us.preservica.com/explorer/explorer.html#properties:IO&{x['xip.reference']}"

    s = natsort.natsorted(source)
    t = natsort.natsorted(target)

    with open(f'{csv_file_audit}', 'w', newline='') as csvfile:
        writer = csv.writer(csvfile, delimiter=',', quotechar='|', quoting=csv.QUOTE_MINIMAL)
        writer.writerow(['Source Data Folders', 'Source Folder Link', 'New Assets', 'New Asset Link', 'Match'])
        for h in itertools.zip_longest(s, t, fillvalue='*****'):
            a: str = h[0]
            b: str = h[1]
            if (a in source_map) and (b in target_map):
                writer.writerow([a, source_map[a], b, target_map[b],  a == b])
            if (a not in source_map) and (b in target_map):
                writer.writerow([a, "", b, target_map[b],  a == b])
            if (a  in source_map) and (b not in target_map):
                writer.writerow([a, source_map[a], b, "",  a == b])
