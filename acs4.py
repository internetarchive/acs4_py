#!/usr/bin/env python

"""
Copyright(c)2010 Internet Archive. Software license AGPL version 3.

Entry points - call from command line, or see:
queryresourceitems, upload, request and mint.

"""


import sys
import re
import os
import math
import httplib
import urllib
from lxml import etree
from lxml import objectify
from StringIO import StringIO
import base64
import hmac
import hashlib
import random
import time
import datetime
import uuid


AdeptNS = 'http://ns.adobe.com/adept'
AdeptNSBracketed = '{' + AdeptNS + '}'
default_distributor = 'urn:uuid:00000000-0000-0000-0000-000000000001'
defaultport = 8080
debug = False
dry_run = False

# Show information about request serialization, for debugging
# hmac issues
show_serialization = False

# Set this to a string to remove variable elements from the generated requests,
# for debugging hmac / serialization issues.
nonce = None

class Acs4Exception(Exception):
    pass

def main(argv):
    import optparse

    class MyParser(optparse.OptionParser):
        """ allows non-word-wrapped help epilog """
        def format_epilog(self, formatter):
            return self.epilog

    parser = MyParser(usage='usage: %prog [options] server_url action [arg]',
                      version='%prog 0.1',
                      description='Interact with ACS.',
                      epilog="""

python acs4.py server mint --distributor='uuid' --resource='uuid'
python acs4.py server queryresourceitems # requires --distributor=defaultdist
python acs4.py server upload [filename] (or --datapath=/server/path/book.epub)
python acs4.py server request api request_type
        api is: (id is:)
                DistributionRights      (distributor + resource)
                Distributor             (distributor)
                Fulfillment             (fulfillment)
                FulfillmentItem         (fulfillment)
                License                 (user + resource)
                ResourceItem            (resource + item)
                ResourceKey             (resource)
                UserPublic              (user)

        request_type is: 'get count create delete update'

        USE WITH CARE, this can break your acs4 install!
        
""")

    parser.add_option('-p', '--password',
                      action='store',
                      help='ACS4 password')
    parser.add_option('--permissions',
                      action='store',
                      help='xml file of ACS4 permissions - for upload and request')
    parser.add_option('--datapath',
                      action='store',
                      help='server data path to use with upload')
    parser.add_option('-d', '--debug',
                      action='store_true',
                      help='Print debugging output')
    parser.add_option('--dry_run',
                      action='store_true',
                      help='Don\'t post to server')
    parser.add_option('--port',
                      default=defaultport,
                      action='store',
                      help='Server port to use (default 8080)')

    # also repeat these below, near 'dynamic'
    request_arg_names = ['distributor',
                         'resource',
                         'distributionType',
                         'available',
                         'returnable',
                         'resourceItem',
                         'notifyURL',
                         'user',
                         ]
    for name in request_arg_names:
        parser.add_option('--' + name,
                               action='store',
                               help=name + ' argument for request')

    opts, args = parser.parse_args(argv)

    if opts.permissions:
        opts.permissions = open(opts.permissions).read()
    if opts.debug:
        global debug
        debug = True
    if opts.dry_run:
        global dry_run
        dry_run = True

    if not opts.password:
        parser.error('We think a password arg might be required')
    if len(args) < 2:
        parser.error('Please supply at least server and action args')

    server = args[0]
    action = args[1].lower()

    actions = ['queryresourceitems', 'upload', 'request', 'mint']
    if not action in actions:
        parser.error('action arg should be one of ' + ', '.join(actions))
        
    if action == 'queryresourceitems':
        print queryresourceitems(server, opts.password,
                                 distributor=opts.distributor,
                                 port=opts.port)
    elif action == 'upload':
        fh = None
        if len(args) == 3:
            if opts.datapath is not None:
                parser.error('--datapath (path to remote file) and filename both supplied.')
            fh = open(args[2])
        elif len(args) == 2:
            if opts.datapath is None:
                parser.error('please supply filename or --datapath argument')
        else:
            parser.error('Wrong number of args supplied to upload action')
        print upload(server, fh, opts.password,
                     datapath=opts.datapath,
                     permissions=opts.permissions,
                     port=opts.port)
    elif action == 'request':
        request_types = ['get', 'count', 'create', 'delete', 'update']
        joined = ', '.join(request_types)
        if len(args) != 4:
            parser.error('For "request" action, please supply server, "request", web_api, request_type - where web_api is e.g. DistributionRights, and request_type is one of ' + joined)
        api = args[2]
        request_type = args[3].lower()
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
        request_args['notifyURL'] = opts.notifyURL
        request_args['user'] = opts.user
        request(server, api, request_type, request_args, opts.password,
                permissions=opts.permissions,
                port=opts.port)

    elif action == 'mint':
        distinfo = get_distributor_info(server, opts.password, opts.distributor,
                                        port=opts.port)
        secret = distinfo['sharedSecret']
        name = distinfo['name']
        print mint(server, secret, opts.resourceItem, 'enterloan', name,
                   port=opts.port)
    parser.destroy()


def mint(server, secret, resource, action, ordersource, rights=None, orderid=None, port=defaultport):
    """Create an acs4 download link.

    'secret' should be the base-64 encoded secret key string for the
    resource distributor.  This can be obtained by calling
    get_distributor_info and using sharedSecret from the result.

    Arguments:
    server
    secret - distributor_info['sharedSecret']
    resource - the acs4 resource uuid
    action - 'enterloan' or 'enterorder'
    ordersource - 'My Store Name', or distributor_info['name']

    Keyword arguments:

    rights - Used to further restrict rights on downloaded resource.
        See Content Server Technical Reference, section 3.4 for
        details on this string.  To expire the book in one day, and
        allow printing 2 pages per hour, specify
        rights='$lrt#86400$$prn#2#3600$'  Yep.  Note that this can't
        extend the rights already granted in ACS4.

    orderid - an opaque token, 'orderid' in generated link, notifyurl
        posts.  Note that this *must* be unique (within the expiration
        window) or loan fulfillment will fail.  If not supplied, a
        random one will be generated.

    """

    if not action in ['enterloan', 'enterorder']:
        raise Acs4Exception('mint action argument should be enterloan or enterorder')
    
    if orderid is None:
        orderid = uuid.uuid4().urn
    argsobj = {
        'action': action,
        'ordersource': ordersource,
        'orderid': orderid,
        'resid': resource,
        'gbauthdate': make_expiration(0),
        'dateval': str(int(time.time())),
        'gblver': 4
        }
    if rights is not None:
        argsobj['rights'] = rights
    urlargs = urllib.urlencode(argsobj)
    mac = hmac.new(base64.b64decode(secret), urlargs, hashlib.sha1)
    auth = mac.hexdigest()
    portstr = (':' + str(port)) if port is not 80 else ''
    return ('http://' + server + portstr + '/fulfillment/URLLink.acsm?'
            + urlargs + '&auth=' + auth)
    

def get_distributor_info(server, password, distributor, port=defaultport):
    request_args = { 'distributor':distributor }
    reply = request(server, 'Distributor', 'get', request_args, password)
    obj = xml_to_py(reply)
    try:
        result = obj['distributorData']
    except KeyError:
        raise Acs4Exception('Query result did not have the expected structure:\n' + reply)
    return result


def request(server, api, action, request_args, password,
            permissions=None, port=defaultport):
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="no"?>' +
        '<request action="' + action
           + '" auth="builtin" xmlns="http://ns.adobe.com/adept"/>')

    tree = etree.parse(StringIO(xml))
    root_el = tree.getroot()
    add_envelope(root_el, password)
    api_el_name = api[0].lower() + api[1:]

    # Several requests require a subelement name that's different from
    # the API; these are special-cased here.  It's not clear if
    # there's any system to them.
    if api_el_name == 'resourceItem':
        api_el_name += 'Info'
    if api_el_name in ('distributor', 'license'
                       'fulfillment', 'fulfillmentItem'):
        api_el_name += 'Data'
    api_el = etree.SubElement(root_el, api_el_name)

    if permissions is not None:
        perms_el = read_perms_xml(permissions)
        api_el.append(perms_el)

    for key in request_args.keys():
        if request_args[key]:
            etree.SubElement(api_el, key).text = request_args[key]

    etree.SubElement(root_el, 'hmac').text = make_hmac(password, root_el)
    request = etree.tostring(tree,
                             pretty_print=True,
                             encoding='utf-8')
    if debug:
        print request
    if dry_run:
        return None
    response = post(request, server, port,
                    '/admin/Manage' + api[0].upper() + api[1:])
    if debug:
        print response
    return response


def upload(server, filehandle, password,
           datapath=None, port=defaultport, permissions=None):
    """Upload a file to ACS4.

    Arguments:
    server
    filehandle
    password

    Keyword arguments:
    port

    permissions - This should be xml describing the item permissions,
        if any.  The best way to get this is to configure a sample
        book in the ACS4 admin console UI, then copy it here.  Any
        valid ACS4 xml fragment that includes a 'permissions' element
        should work.

    """

    xml = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<package xmlns="http://ns.adobe.com/adept"/>
"""
    tree = etree.parse(StringIO(xml))
    root_el = tree.getroot()

    if filehandle is not None:
        etree.SubElement(root_el, 'data').text = base64.encodestring(filehandle.read())
    else:
        etree.SubElement(root_el, 'dataPath').text = datapath

    if permissions is not None:
        perms_el = read_perms_xml(permissions)
        root_el.append(perms_el)

    add_envelope(root_el, password)
    etree.SubElement(root_el, 'hmac').text = make_hmac(password, root_el)

    request = etree.tostring(tree,
                             pretty_print=True,
                             encoding='utf-8')
    if debug:
        print request
    if dry_run:
        return None
    response = post(request, server, port, '/packaging/Package')
    if debug:
        print response
    obj = xml_to_py(response)
    return obj


def queryresourceitems(server, password, distributor=None, port=defaultport, debug=False):
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<request xmlns="http://ns.adobe.com/adept"/>
"""
    tree = etree.parse(StringIO(xml))
    root_el = tree.getroot()
    if distributor is not None:
        etree.SubElement(root_el, 'distributor').text = distributor;
    add_envelope(root_el, password, debug=debug)
    etree.SubElement(root_el, 'QueryResourceItems')
    etree.SubElement(root_el, 'hmac').text = make_hmac(password, root_el)
    request = etree.tostring(tree,
                             pretty_print=True,
                             encoding='utf-8')
    if debug:
        print request
    if dry_run:
        return None
    response = post(request, server, port, '/admin/QueryResourceItems')
    if debug:
        print response
    return response


def post(request, server, port, api_path):
    headers = { 'Content-Type': 'application/vnd.adobe.adept+xml' }
    conn = httplib.HTTPConnection(server, port)
    conn.request('POST', api_path, request, headers)
    return conn.getresponse().read()


def add_envelope(el, password, debug=None):
    etree.SubElement(el, 'expiration').text = make_expiration(3000) if nonce is None else nonce
    etree.SubElement(el, 'nonce').text = make_nonce() if nonce is None else nonce 


def make_expiration(seconds):
    t = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def make_nonce():
    return base64.b64encode(os.urandom(20))[:20]


def make_hmac(password, el):
    passhasher = hashlib.sha1()
    passhasher.update(password)
    passhash = passhasher.digest()
    mac = hmac.new(passhash, '', hashlib.sha1)

    if show_serialization:
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


def read_perms_xml(permissions):
    ncparser = etree.XMLParser(remove_comments=True)
    perms_arg_el = etree.fromstring(permissions, parser=ncparser)
    if (perms_arg_el.tag == 'permissions' or
        perms_arg_el.tag == AdeptNSBracketed + 'permissions'):
        perms_el = perms_arg_el
    else:
        perms_el = perms_arg_el.find('.//' + AdeptNSBracketed + 'permissions')
    if perms_el is None:
        perms_el = perms_arg_el.find('.//permissions')
    if perms_el is None:
        raise Acs4Exception('No permissions element in supplied permissions xml')
    return perms_el
    

def xml_to_py(xml_string):
    o = objectify.fromstring(xml_string)
    return objectified_to_py(o)


def objectified_to_py(o):
    if isinstance(o, objectify.IntElement):
        return int(o)
    if isinstance(o, objectify.NumberElement) or isinstance(o, objectify.FloatElement):
        return float(o)
    if isinstance(o, objectify.ObjectifiedDataElement):
        return str(o)
    if hasattr(o, '__dict__'):
        result = o.__dict__
        for key, value in result.iteritems():
            result[key] = objectified_to_py(value)
        return result
    return o


if __name__ == '__main__':
    main(sys.argv[1:])
