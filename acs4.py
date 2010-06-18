#!/usr/bin/env python

"""
Copyright(c)2010 Internet Archive. Software license AGPL version 3.
"""


import sys
import re
import os
import math
import httplib
import urllib
from lxml import etree
from StringIO import StringIO
import base64
import hmac
import hashlib

# from  pydbgr.api import debug
# debug()

AdeptNS = 'http://ns.adobe.com/adept'
default_dist = 'urn:uuid:00000000-0000-0000-0000-000000000001'

# Set this to a string to remove variable elements from the generated requests,
# for debugging hmac / serialization issues.
nonce = None

"""
python ../acs4.py --password='' --debug upload ia331529.us.archive.org ../logofcowboynarra00adamuoft.epub
python ../acs4.py --password='' --debug queryresourceitems ia331529.us.archive.org urn:uuid:00000000-0000-0000-0000-000000000001

request --resource=(some book) --distributor=(iadistrutor) --distributionType=buy $SERVER DistributionRights create



needed: get book info (uuid (x distributor?))
book available?

(do we get notification on book return?)
(something that polls?)

? what latency ballpark for basic book queries?

mint a url - (for a particular ADE user)

? how many copies available for a given book?  How to spec more?

possible to keep socket open?



book info
mint a url (from book uuid)


"""


def main(argv):
    import optparse

    # borrowed from http://stackoverflow.com/questions/1857346/python-optparse-how-to-include-additional-info-in-usage-output
    class MyParser(optparse.OptionParser):
        def format_epilog(self, formatter):
            return self.epilog

    parser = MyParser(usage='usage: %prog [options] server_url action [arg]',
                      version='%prog 0.1',
                      description='Interact with ACS.',
                      epilog="""
python acs4.py server queryresourceitems # requires --distributor=defaultdist
python acs4.py server upload filename
python acs4.py server request api request_type
""")


    parser.add_option('-p', '--password',
                      action='store',
                      help='ACS password')
    parser.add_option('-d', '--debug',
                      action='store_true',
                      help='Print debugging output')

    # also repeat these below, near 'dynamic'
    request_arg_names = ['distributor',
                         'resource',
                         'distributionType',
                         'available',
                         'returnable',
                         'resourceItem'
                         ]
    for name in request_arg_names:
        parser.add_option('--' + name,
                               action='store',
                               help=name + ' argument for request')

    opts, args = parser.parse_args(argv)

    if not opts.password:
        parser.error('We think a password arg might be required')
    if len(args) < 2:
        parser.error('Please supply at least server and action args')

    server = args[0]
    action = args[1].lower()

    actions = ['queryresourceitems', 'upload', 'request']
    if not action in actions:
        parser.error('action arg should be one of ' + ', '.join(actions))
        
    if action == 'queryresourceitems':
        queryresourceitems(server, opts.distributor, opts.password, opts.debug)
    elif action == 'upload':
        if len(args) != 3:
            parser.error('For "upload" action, please supply 3 args: server, "upload", filename')
        filename = args[2]
        upload(server, filename, opts.password, opts.debug)
    elif action == 'request':
        request_types = ['get', 'count', 'create', 'delete', 'update']
        joined = ', '.join(request_types)
        if len(args) != 4:
            parser.error('For "request" action, please supply server, "request", web_api, request_type - where web_api is e.g. DistributionRights, and request_type is one of ' + joined)
        api = args[2]
        request_type = args[3]
        if not request_type in request_types:
            parser.error('Request type should be one of ' + joined)
        request_args = {}
        
        # TODO make this dynamic.  But opts is an optparse.Values, and
        # doesn't have __getitem__!  request_args = dict([(name,
        # opts[name]) for name in request_arg_names])
        request_args['distributor'] = opts.distributor
        request_args['resource'] = opts.resource
        request_args['distributionType'] = opts.distributionType
        request_args['available'] = opts.available
        request_args['returnable'] = opts.returnable
        request_args['resourceItem'] = opts.resourceItem

        request(server, api, request_type, request_args, opts.password, opts.debug)
    parser.destroy()


def request(server, api, action, request_args, password, debug):
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="no"?>' +
        '<request action="' + action + '" auth="builtin" xmlns="http://ns.adobe.com/adept"/>')

    print xml
    tree = etree.parse(StringIO(xml))
    root_el = tree.getroot()
    add_envelope(root_el, password, debug=debug)
    api_el_name = api[0].lower() + api[1:]
    if api_el_name == 'resourceItem':
        api_el_name += 'Info'
    if api_el_name == 'distributor':
        api_el_name += 'Data'
    api_el = etree.SubElement(root_el, api_el_name)

    for key in request_args.keys():
        if request_args[key]:
            etree.SubElement(api_el, key).text = request_args[key]

    # perms = etree.SubElement(api_el, 'permissions')
    # disp =  etree.SubElement(perms, 'display')
    # etree.SubElement(disp, 'duration').text ='181'
    # etree.SubElement(perms, 'excerpt')
    # etree.SubElement(perms, 'print')

    etree.SubElement(root_el, 'hmac').text = make_hmac(password, root_el, debug)
    request = etree.tostring(tree,
                             pretty_print=True,
                             encoding='utf-8')
    if debug:
        print request

    response = post(request, server, '/admin/Manage' + api[0].upper() + api[1:]) # api here
    print response


def upload(server, filename, password, debug=None):
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<package xmlns="http://ns.adobe.com/adept"/>
"""
    tree = etree.parse(StringIO(xml))
    root_el = tree.getroot()

    etree.SubElement(root_el, 'data').text = base64.encodestring(open(filename).read())

    add_envelope(root_el, password, debug=debug)
    etree.SubElement(root_el, 'hmac').text = make_hmac(password, root_el, debug)

    request = etree.tostring(tree,
                             pretty_print=True,
                             encoding='utf-8')

    if debug:
        print request
    response = post(request, server, '/packaging/Package')
    print response


def queryresourceitems(server, distributor, password, debug=None):
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<request xmlns="http://ns.adobe.com/adept"/>
"""
    tree = etree.parse(StringIO(xml))
    root_el = tree.getroot()
    etree.SubElement(root_el, 'distributor').text = distributor;
    add_envelope(root_el, password, debug=debug)
    etree.SubElement(root_el, 'QueryResourceItems')
    etree.SubElement(root_el, 'hmac').text = make_hmac(password, root_el, debug)
    request = etree.tostring(tree,
                             pretty_print=True,
                             encoding='utf-8')
    if debug:
        print request
    response = post(request, server, '/admin/QueryResourceItems')
    print response


def post(request, server, api_path):
    headers = { 'Content-Type': 'application/vnd.adobe.adept+xml' }
    conn = httplib.HTTPConnection(server, 8080)
    conn.request('POST', api_path, request, headers)
    return conn.getresponse().read()


def add_envelope(el, password, debug=None):
    etree.SubElement(el, 'expiration').text = make_expiration(3000) if nonce is None else nonce
    etree.SubElement(el, 'nonce').text = make_nonce() if nonce is None else nonce 


def make_expiration(seconds):
    import datetime
    t = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def make_nonce():
    return base64.b64encode(os.urandom(20))[:20]


def make_hmac(password, el, debug=None):
    passhasher = hashlib.sha1()
    passhasher.update(password)
    passhash = passhasher.digest()
    mac = hmac.new(passhash, '', hashlib.sha1)

    if debug:
        logger = debug_consumer()
        serialize_el(el, logger)
        print logger.dump()

    serialize_el(el, mac)

    return base64.b64encode(mac.digest())


# Serializes the xml element and children a la ACS4, and calls
# 'update' on consumer with same
def serialize_el(el, consumer):
    def consume_str(s):
        # TODO might need to worry about unicode (s.encode('utf-8'))
        # if e.g. metadata has unicode.
        consumer.update(chr((len(s) >> 8) & 0xff))
        consumer.update(chr((len(s) & 0xff)))
        consumer.update(s)
                        
    BEGIN_ELEMENT = '\x01'
    END_ATTRIBUTES = '\x02'
    END_ELEMENT = '\x03'
    TEXT_NODE = '\x04'
    ATTRIBUTE = '\x05'

    # TODO needs reexamine, as namespace doesn't seem to be present in
    # subnodes.  Using el.nsmap - should verify behavior in presence
    # of other namespaces.

    p = re.compile(r'(\{(.*)\})?(.*)')
    m = p.match(el.tag)
    namespace = None
    namespace = m.group(2)
    namespace = namespace if namespace is not None else ''
    localname = m.group(3)
    namespace = el.nsmap[None]

    if namespace == AdeptNS and localname == 'signature':
        return
    
    consumer.update(BEGIN_ELEMENT)
    consume_str(namespace)
    consume_str(localname)

    # TODO sort: "Attributes are sorted first by their namespaces and
    # then by their names; sorting is done bytewise on UTF-8
    # representations."

    keys = el.attrib.keys()
    keys.sort()
    for attname in keys:
        consumer.update(ATTRIBUTE)
        consume_str("") # TODO element namespace
        consume_str(attname)
        consume_str(el.attrib[attname])

    # TODO serialize attributes

    consumer.update(END_ATTRIBUTES)

    if el.text:
        text = el.text.strip()
        length = len(text)
        if length > 0:
            i = 0
            remains = 0
            while True:
                remains = length - i
                if remains > 0x7fff: # TODO test with smaller value
                    remains = 0x7fff
                consumer.update(TEXT_NODE)
                consume_str(text[i: i + remains])
                i += remains
                if i >= length:
                    break
    for child in el:
        serialize_el(child, consumer)

    consumer.update(END_ELEMENT)


class debug_consumer:
    def __init__(self):
        self.s = ''
    def update(self, s):
        serialize_names = [ '',
                             'BEGIN_ELEMENT',
                             'END_ATTRIBUTES',
                             'END_ELEMENT',
                             'TEXT_NODE',
                             'ATTRIBUTE' ]
        if len(s) == 1:
            self.s += hex(ord(s))
            if ord(s) >= 1 and ord(s) <= 5:
                self.s += ' ' + serialize_names[ord(s)]
        else:
            self.s += s
        self.s += '\n'
    def dump(self):
        return self.s


if __name__ == '__main__':
    main(sys.argv[1:])
