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
expiration_secs = 1800

# print generated requests and server results
debug = False

# Don't communicate with the server
dry_run = False

# Show information about request serialization, for debugging
# hmac issues
show_serialization = False

# Set this to a string to remove variable elements from the generated
# requests, for debugging hmac / serialization issues.
nonce = None

# Ditto.  Sample: 2010-06-26T07:35:58+00:00
expiration = None

class Acs4Exception(Exception):
    pass

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

    # replace with string format?
    # construct with urlparse.unsplit()
    return ('http://' + server + portstr + '/fulfillment/URLLink.acsm?'
            + urlargs + '&auth=' + auth)
    

def request(server, api, action, request_args, password,
            permissions=None, port=defaultport):
    """Make a xml-mediated DB request to the ACS4 server.

    Arguments:
    server

    api - one of: (unique id required to e.g. get a single instance)
                DistributionRights      (distributor + resource)
                Distributor             (distributor)
                Fulfillment             (fulfillment)
                FulfillmentItem         (fulfillment)
                License                 (user + resource)
                ResourceItem            (resource + item)
                ResourceKey             (resource)
                UserPublic              (user)

    action - 'get count create delete update'

    request_args - a dict of elements to be added as children of the
        'api element' (e.g. distributionRights).  Note *all* must be
        supplied for 'update' action, or the remainder will be nulled.

    Keyword arguments:
    port

    permissions - This should be xml describing the item permissions,
        if any.  The best way to get this is to configure a sample
        book in the ACS4 admin console UI, then copy it here.  Any
        valid ACS4 xml fragment that includes a 'permissions' element
        should work.

    USE WITH CARE, this API can break your acs4 install!
    """

    root_el = etree.Element('request',
                            { 'action': action, 'auth': 'builtin' },
                            nsmap={None: AdeptNS})
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

    for key in request_args.keys():
        if request_args[key]:
            if key == 'permissions':
                # add permissions (an xml string) only if keyword arg
                # isn't supplied
                if permissions is None:
                    perms_el = read_xml(request_args[key], 'permissions')
                    api_el.append(perms_el)
            elif key == 'metadata':
                try:
                    meta_el = o_to_meta_xml(request_args[key])
                except TypeError:
                    meta_el = read_xml(request_args[key], 'metadata')
                api_el.append(meta_el)
            else:
                etree.SubElement(api_el, key).text = str(request_args[key])

    if permissions is not None:
        perms_el = read_xml(permissions, 'permissions')
        api_el.append(perms_el)

    response = post(root_el, server, port, password,
                    '/admin/Manage' + api[0].upper() + api[1:])

    return response


def upload(server, filehandle, password,
           datapath=None, port=defaultport,
           metadata=None, permissions=None):
    """Upload a file to ACS4.

    Arguments:
    server
    filehandle
    password

    Keyword arguments:
    port

    datapath - Path ON SERVER to file to be packaged.  When this is supplied,
        filehandle should be None.

    permissions - This should be xml describing the item permissions,
        if any.  The best way to get this is to configure a sample
        book in the ACS4 admin console UI, then copy it here.  Any
        valid ACS4 xml fragment that includes a 'permissions' element
        should work.

    metadata - Similar to permissions.  A flat name : value dict is
        also accepted.  ACS4 will fill in missing values from the media.

    """

    root_el = etree.Element('package', nsmap={None: AdeptNS})

    if filehandle is not None:
        etree.SubElement(root_el, 'data').text = base64.encodestring(filehandle.read())
    else:
        etree.SubElement(root_el, 'dataPath').text = datapath

    if permissions is not None:
        perms_el = read_xml(permissions, 'permissions')
        root_el.append(perms_el)
    if metadata is not None:
        try:
            meta_el = o_to_meta_xml(metadata)
        except TypeError:
            meta_el = read_xml(metadata, 'metadata')
        root_el.append(meta_el)

    response = post(root_el, server, port, password,
                    '/packaging/Package')

    obj = xml_to_py(response)
    return obj


def queryresourceitems(server, password, distributor=None, port=defaultport):
    el = etree.Element('request', nsmap={None: AdeptNS})
    if distributor is not None:
        etree.SubElement(el, 'distributor').text = distributor;
    etree.SubElement(el, 'QueryResourceItems')
    response = post(el, server, port, password,
                    '/admin/QueryResourceItems')
    return response


def post(xml, server, port, password, api_path):
    """ sign and post supplied xml to server at api_path, returning the result.

    Adds expiration, nonce and hmac to post.

    Parses the reply for an error response, and throws an exception
    one is found.

    """

    # convert provided string to etree
    if isinstance(xml, basestring):
        xml = etree.fromstring(xml)

    # Add 'envelope' and hmac
    post_expiration = make_expiration(expiration_secs) if expiration is None else expiration
    etree.SubElement(xml, 'expiration').text = post_expiration
    post_nonce = base64.b64encode(os.urandom(20))[:20] if nonce is None else nonce
    etree.SubElement(xml, 'nonce').text = post_nonce
    etree.SubElement(xml, 'hmac').text = make_hmac(password, xml)

    request = etree.tostring(xml,
                             pretty_print=True,
                             encoding='utf-8')
    if debug:
        print request
    if dry_run:
        return None

    headers = { 'Content-Type': 'application/vnd.adobe.adept+xml' }
    conn = httplib.HTTPConnection(server, port)
    conn.request('POST', api_path, request, headers)
    result = conn.getresponse().read()
    conn.close()

    if debug:
        print result

    xml = etree.fromstring(result)
    # TODO is there a way to get first el without parsing the whole thing?
    if xml.tag == AdeptNSBracketed + 'error' or xml.tag == 'error':
        raise Acs4Exception(xml.get('data'))
    # TODO is reply always 'error' or 'response' ?
    # - so - if reponse isn't 'response', then error?
    return result


def get_distributor_info(server, password, distributor, port=defaultport):
    request_args = { 'distributor': distributor }
    reply = request(server, 'Distributor', 'get', request_args, password)
    obj = xml_to_py(reply)
    try:
        result = obj['distributorData']
    except KeyError:
        raise Acs4Exception('Query result did not have the expected structure:\n' + reply)
    return result


def get_resourcekey_info(server, password, resource, port=defaultport):
    """ Get a dict of information describing a resource.

    This is where permissions are handled in the ACS4 database.

    Note that this is in the 'operator inventory', not as assigned to
    a specific distributor.

    The resource permissions are not recursively parsed, but are
    returned as a string.

    """
    request_args = { 'resource': resource }
    reply = request(server, 'ResourceKey', 'get', request_args, password, port=port)
    obj = xml_to_py(reply)
    try:
        result = obj['resourceKey']
    except KeyError:
        raise Acs4Exception('Query result did not have the expected structure:\n' + reply)
    return result


def set_resourcekey_info(server, password, info, port=defaultport):
    """ Set information for a resource, given a dict describing it.

    The resource_info argument should be an object as returned from
    set_resource_info().

    """
    reply = request(server, 'ResourceKey', 'update', info, password, port=port)
    obj = xml_to_py(reply)
    try:
        result = obj['resourceKey']
    except KeyError:
        raise Acs4Exception('Query result did not have the expected structure:\n' + reply)
    return result


def get_resourceitem_info(server, password, resource, port=defaultport):
    # TODO handle multiple return values
    # request_args = { }
    request_args = { 'resource': resource }
    reply = request(server, 'ResourceItem', 'get', request_args, password, port=port)
    obj = xml_to_py(reply)
    try:
        result = obj['resourceItemInfo']
    except KeyError:
        raise Acs4Exception('Query result did not have the expected structure:\n' + reply)
    return result


def set_resourceitem_info(server, password, info, port=defaultport):
    """ note that acs4 won't let this change metadata info """

    reply = request(server, 'ResourceItem', 'update', info, password, port=port)
    obj = xml_to_py(reply)
    try:
        result = obj['resourceItemInfo']
    except KeyError:
        raise Acs4Exception('Query result did not have the expected structure:\n' + reply)
    return result


def make_expiration(seconds):
    t = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def make_hmac(password, el):
    """ Serialize an element and make an hmac with it and the given password """
    
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


def serialize_el(el, consumer):
    """ Recursively serialize the given element to supplied consumer """

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

    p = re.compile(r'(\{(.*)\})?(.*)')
    m = p.match(el.tag)
    namespace = m.group(2)
    localname = m.group(3)
    if namespace is None:
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


def read_xml(xml, nodename):
    # ??? make read_xml front for converting metadata, perms?

    """ Parse xml (a string?) and pluck out a named subelement. """
    # if xml is etree._Element
    # - instead: if has nodetype
    # - or whatever
    # - or hasattr
    # or just start with isinstance basestring
    if xml.__class__ == etree._Element:
        # accept an etree Element
        # TODO fix unpythonic above test?
        arg_el = xml
    else:
        ncparser = etree.XMLParser(remove_comments=True)
        arg_el = etree.fromstring(xml, parser=ncparser)
    if (arg_el.tag == nodename or
        arg_el.tag == AdeptNSBracketed + nodename):
        el = arg_el
    else:
        el = arg_el.find('.//' + AdeptNSBracketed + nodename)
    if el is None:
        el = arg_el.find('.//' + nodename)
    if el is None:
        # string formatting here
        raise Acs4Exception('No ' + nodename + 'element in supplied '
                            + nodename + ' xml')
    return el


def o_to_meta_xml(o):
    """ Convert a dict of metadata into a valid dc metadata element """
    dc = 'http://purl.org/dc/elements/1.1/'
    dcb = '{' + dc + '}'
    meta_el = etree.Element('metadata', nsmap = {'dc': dc})
    for k, v in o.iteritems():
        el = etree.SubElement(meta_el, dcb + k).text = v
    return meta_el


def meta_xml_to_o(xml):
    """ Convert an xml string containing a metadata element to a dict

    Note that this is *not* general, as only one of any repeated
    metadata element (which *is* allowed) will end up in the dict.

    """
    meta_el = read_xml(xml, 'metadata')
    result = {}
    for el in meta_el:
        p = re.compile(r'(\{.*\})?(.*)')
        m = p.match(el.tag)
        localname = m.group(2)
        result[localname] = el.text
    return result


def xml_to_py(xml_string):
    o = objectify.fromstring(xml_string)
    return objectified_to_py(o)


def objectified_to_py(o):
    """ Make a dict from an 'objectified' representation of xml.

    Special-case 'permissions' elements - return those as strings.

    """
    if isinstance(o, objectify.IntElement):
        return int(o)
    if isinstance(o, (objectify.NumberElement, objectify.FloatElement)):
        return float(o)
    if isinstance(o, objectify.ObjectifiedDataElement):
        return str(o)
    if hasattr(o, '__dict__'):
        if o.tag in (AdeptNSBracketed + 'permissions', 'permissions'):
            return etree.tostring(o, pretty_print=True)
        elif o.tag in (AdeptNSBracketed + 'metadata', 'metadata'):
            return meta_xml_to_o(etree.tostring(o))
        else:
            result = o.__dict__
            for key, value in result.iteritems():
                result[key] = objectified_to_py(value)
            return result
    return o


if __name__ == '__main__':
    raise Exception('not to be called as a __main__')
