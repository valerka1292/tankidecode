RESOURCE_BASE = 'http://s.eu.tankionline.com'
TYPE_BY_FILE = {
    'proplibs.xml': 7,
    'map.xml': 7,
    'image.tnk': 10,
    'image.webp': 10, # HTML5
    'image.tara': 11,
    'image_x15.tnk': 12,
    'en.tnk': 13
}
FILES_BY_TYPE = {
    7: ['proplibs.xml', 'map.xml'],
    9: ['image.tnk', 'image.webp'],
    10: ['image.tnk', 'image.webp'],
    11: ['image.tnk', 'image.tara', 'image.webp', 'frame.json'],
    12: ['image_x15.tnk']
}

def get_resource_path(resourceId, version):
    parts = (
        resourceId >> 32,
        (resourceId >> 16) & 0xFFFF,
        (resourceId >> 8) & 0xFF,
        resourceId & 0xFF,
        version
    )
    return '/%o/%o/%o/%o/%o/' % parts

def get_resource_urls(resourceId, version, resourceType):
    path = get_resource_path(resourceId, version)
    urls = list()
    for fname in FILES_BY_TYPE[resourceType]:
        urls.append(''.join((RESOURCE_BASE, path, fname)))
    return urls

def parse_resource_url(url):
    _, *parts, fname = url.rsplit('/', 6)
    *parts, version = map(lambda x: int(x, 8), parts)
    resourceId = ((parts[0] & 0xFFFFFFFF) << 32) + ((parts[1] & 0xFFFF) << 16)\
        + ((parts[2] & 0xFF) << 8) + (parts[3] & 0xFF)
    return resourceId, version, TYPE_BY_FILE.get(fname, None)

if __name__ == '__main__':
    urls = get_resource_urls(500305955, 1587125762730, 7)
    print(urls)
    print(parse_resource_url(urls[0]))
