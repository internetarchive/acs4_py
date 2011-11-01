"""
Copyright(c)2010 Internet Archive. Software license AGPL version 3.

A library for interacting with acs4 xml API.  See example use at bottom.

"""

# skip translation layer, and just take input dicts?
# (iow, skip keyword args!)
# means even less guidance...
# tho if it were easy xlate of monitor output...

import sys
import re
import os
import math
import httplib
import urllib
from lxml import etree
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
defaultport = 80
expiration_secs = 1800 # expiration time for a given nonce? needs note

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


def add_hmac_envelope(xml, password):
    """ Compute and add expiration, nonce and hmac elements to supplied xml.
    xml can be a string or an etree element. """
    # convert provided string to etree
    if isinstance(xml, basestring):
        xml = etree.fromstring(xml)

    # Add 'envelope' and hmac
    post_expiration = make_expiration(expiration_secs) \
        if expiration is None else expiration
    etree.SubElement(xml, 'expiration').text = post_expiration
    post_nonce = base64.b64encode(os.urandom(20))[:20] \
        if nonce is None else nonce
    etree.SubElement(xml, 'nonce').text = post_nonce
    etree.SubElement(xml, 'hmac').text = make_hmac(xml, password)

    return etree.tostring(xml,
                          pretty_print=True,
                          encoding='utf-8')


def post(request, server, port, api_path):
    """ post supplied request to server at api_path, returning the result.

    Parses the reply for an error response, and throws an exception
    one is found.

    """

    if debug:
        print api_path
        print request
    if dry_run:
        return None

    headers = { 'Content-Type': 'application/vnd.adobe.adept+xml' }
    conn = httplib.HTTPConnection(server, port)
    conn.request('POST', api_path, request, headers)

    try:
        response_str = conn.getresponse().read()
        response = etree.fromstring(response_str) # XXX could read directly?
    except etree.XMLSyntaxError:
        raise Acs4Exception("Couldn't parse server response as XML: "
                            + response_str)
    conn.close()

    if debug:
        print response_str

    if response.tag == etree.QName(AdeptNS, 'error'):
        raise Acs4Exception(urllib.unquote(response.get('data')))
    return response


def make_secret():
    """ make a random shared secret string suitable for passing to
    ContentServer().update('Distributor', 'create', { 'sharedSecret': str })
    """

    ss = uuid.uuid4().urn
    passhasher = hashlib.sha1()
    passhasher.update(ss)
    passhash = passhasher.digest()
    return base64.b64encode(passhash)


def add_limit_el(el, start, count):
    if start != 0 or count != 0:
        if start != 0 and count == 0:
            raise Acs4Exception('Please provide count when using start')
        if start < 0 or count < 0:
            raise Acs4Exception('Please use positive values '
                                'for count and start')
        limit_el = etree.SubElement(el, 'limit')
        if start != 0:
            etree.SubElement(limit_el, 'start').text = str(start)
        if count != 0:
            etree.SubElement(limit_el, 'count').text = str(count)


def make_expiration(seconds):
    t = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def make_hmac(el, password):
    """ Serialize an element and make an hmac with it and the given password """

    # Accept either a base64-encoded shared secret, or a password
    # string.  If a password string is passed in, hash it.  As it
    # turns out, the ACS4 console password, hashed, is the default
    # distributor's shared secret.

    passhash = None
    if len(password) == 28 and password[-1] == '=':
        try:
            passhash = base64.b64decode(password)
        except TypeError:
            # if it's not a valid base64-encoded string, just move on.
            pass
    if passhash is None:
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

    def consume_str(s, encoding='utf-8'):
        if isinstance(s, unicode):
            s = s.encode(encoding)
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
    #
    # Not yet clear that this is needed at all in acs4 request xml.

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
        ncparser = etree.XMLParser(remove_comments=True,
                                   remove_blank_text=True)
        arg_el = etree.fromstring(xml, parser=ncparser)
    if (arg_el.tag == nodename or
        arg_el.tag == AdeptNSBracketed + nodename):
        el = arg_el
    else:
        el = arg_el.find('.//' + AdeptNSBracketed + nodename)
    if el is None:
        el = arg_el.find('.//' + nodename)
    if el is None:
        raise Acs4Exception('No %s element in supplied xml' % (nodename))
    return el


def decompose_tag(tag):
    p = re.compile(r'(\{(.*)\})?(.*)')
    m = p.match(tag)
    namespace = m.group(2)
    localname = m.group(3)
    return namespace, localname


def el_to_o(el):
    if len(el) == 0:
        if el.tag == AdeptNSBracketed + 'count' or el.tag == 'count':
            result = {}
            for attr in ('initial', 'max', 'incrementInterval'):
                if el.get(attr):
                    result[attr] = el.get(attr)
            return result
        else:
            return el.text
    result = {}
    for kid in el:
        namespace, localname = decompose_tag(kid.tag)
        result[localname] = el_to_o(kid)
        # print localname
        # if localname in result:
        #     # convert to list
        #     result[localname] = [result[localname]]
        # else:
    return result


def o_to_meta_el(o):
    """ Convert a dict of metadata into a valid dc metadata element """
    dc = 'http://purl.org/dc/elements/1.1/'
    dcb = '{' + dc + '}'
    meta_el = etree.Element('metadata', nsmap = {'dc': dc})
    for k, v in o.iteritems():
        etree.SubElement(meta_el, dcb + k).text = v
    return meta_el


def o_to_el(o, name):
    if name == 'metadata':
        return o_to_meta_xml(o)
    el = etree.Element(name)
    for k, v in o.iteritems():
        if isinstance(v, dict):
            el.append(o_to_el(v, k))
        else:
            if name == 'count': # this is the only el with attrs in the schema?
                el.set(k, v)
            else:
                etree.SubElement(el, k).text = v
    return el

## XXX should make port a kwarg with default 80
class ContentServer:
    def __init__(self, host, port, password, distributor=None,
                 sharedSecret=None, name=None):
        self.host = host
        self.port = port
        self.password = password
        self.distributor = distributor # acs uses default distributor if None

        self.sharedSecret = sharedSecret  # get these lazily if not supplied
        self.name = name

    # mint takes a distributor obj?
    # xxx is get_loan_link a better name?  other?
    # xxx should error if can't get shared secret somehow.  don't fall
    # back to null dist.
    def mint(self, resource,
             action='enterloan', rights=None,
             orderid=None, ordersource=None,
             sharedSecret=None):
        """Create an acs4 download link.

        Note that this does not communicate with the server at all,
        but creates a URL that a browser can then visit, to download a
        document of specifications for an acs4 reader to download the
        book.

        Arguments:
        resource - the acs4 resource uuid

        Keyword arguments:
        action - 'enterloan' or 'enterorder'

        rights - Used to further restrict rights on downloaded resource.
            See Content Server Technical Reference, section 3.4 for
            details on this string.  To expire the book in one day, and
            allow printing 2 pages per hour, specify
            rights='$lrt#86400$$prn#2#3600$'  Yep.  Note that this can't
            extend the rights already granted in ACS4.

        orderid - an opaque token, 'orderid' in generated link,
            notifyurl posts.  Note that this *must* be
            (case-insensitively!) unique (within the expiration
            window) or loan fulfillment will fail.  If not supplied, a
            random one will be generated.

        ordersource - 'My Store Name', or distributor_info['name'] if
            not supplied

        sharedSecret - Use this directly instead of looking up
            distributor.  Ordersource should als be supplied.
        """

        # XXX bogus logic
        if sharedSecret is None:
            if self.sharedSecret is None:
                distinfo = self.get_distributor_info()
                sharedSecret = distinfo['sharedSecret']
                self.sharedSecret = sharedSecret
                name = distinfo['name']
                self.name = name
            else:
                sharedSecret = self.sharedSecret

        if ordersource is None:
            ordersource = self.name

        if not action in ['enterloan', 'enterorder']:
            raise Acs4Exception('mint action argument should be '
                                'enterloan or enterorder')

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
        mac = hmac.new(base64.b64decode(sharedSecret),
                       urlargs, hashlib.sha1)
        auth = mac.hexdigest()
        portstr = (':' + str(self.port)) if self.port is not 80 else ''

        # replace with string format?
        # construct with urlparse.unsplit()
        return ('http://' + self.host + portstr + '/fulfillment/URLLink.acsm?'
                + urlargs + '&auth=' + auth)


    def request(self, api, action,
                request_args={}, use_request_args_el=None,
                start=0, count=0, permissions=None,
                resource=None):
        """Make a xml-mediated DB request to the ACS4 server.

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

        Keyword arguments:

        request_args - a dict of elements to be added as children of the
            'api element' (e.g. distributionRights).  Note *all* must be
            supplied for 'update' action, or the remainder will be nulled.

        use_request_args_el - When true, elements generated for keys
            in request_args are added to a new 'args element', with a
            name derived from the api name.  If false, these elements
            are added to the toplevel element.  If None, guess the
            appropriate default.

        permissions - This should be xml describing the item permissions,
            if any.  The best way to get this is to configure a sample
            book in the ACS4 admin console UI, then copy it here.  Any
            valid ACS4 xml fragment that includes a 'permissions' element
            should work.

        USE WITH CARE, this API can break your acs4 install!

        """
        # if use_request_args_el is None:
        #     if action is 'get':
        #         use_request_args_el = False
        #     else:
        #         use_request_args_el = True
        # if use_request_args_el is None:
        #     if api is 'ResourceItem':
        #         use_request_args_el = False
        #     else:
        #         use_request_args_el = True
        use_request_args_el = True

        el = etree.Element('request',
                           { 'action': action, 'auth': 'builtin' },
                           nsmap={None: AdeptNS})

        # XXX NOTE new 'replace' action supported in 4.1 server...
        # syntax is possibly <action>replace</action> - not action='replace'!

        add_limit_el(el, start, count)

        api_el_name = api[0].lower() + api[1:]
        # Several requests require a subelement name that's different from
        # the API; these are special-cased here.  It's not clear if
        # there's any system to them.
        # print api_el_name

        if api_el_name == 'resourceItem':
            api_el_name += 'Info'
        if api_el_name in ('distributor', 'license',
                           'fulfillment', 'fulfillmentItem'):
            api_el_name += 'Data'
        # print api_el_name
        if use_request_args_el is True:
            api_el = etree.SubElement(el, api_el_name)
        else:
            api_el = el

        for key in request_args.keys():
            v = request_args[key]
            if v:
                if key == 'permissions':
                    # add permissions (an xml string) only if keyword arg
                    # isn't supplied
                    if permissions is None:
                        if isinstance(v, dict):
                            perms_el = o_to_el(v, key)
                        else:
                            perms_el = read_xml(v, key)
                        api_el.append(perms_el)
                elif key == 'metadata':
                    if isinstance(v, dict):
                        meta_el = o_to_meta_el(v)
                    else:
                        meta_el = read_xml(v, key)
                    api_el.append(meta_el)
                else:
                    if isinstance(v, dict):
                        sub_el = o_to_el(v, key)
                        api_el.append(sub_el)
                    else:
                        if not isinstance(v, basestring):
                            v = str(v)
                        etree.SubElement(api_el, key).text = v

        if resource is not None:
            resource_el = etree.SubElement(el, 'resource')
            resource_el.text = resource
            el.append(resource_el)
        if permissions is not None:
            perms_el = read_xml(permissions, 'permissions')
            api_el.append(perms_el)

        signed_request = add_hmac_envelope(el, self.password)
        response = post(signed_request, self.host, self.port,
                        '/admin/Manage' + api[0].upper() + api[1:])
        if response is None:
            return None
        if action == 'count':
            return int(response.find('.//' + AdeptNSBracketed + 'count').text)
        return [el_to_o(info_el) for info_el in
                response.findall('.//' + AdeptNSBracketed + api_el_name)]


    def upload(self,
               filehandle=None, dataPath=None, # one of these is required
               resource=None, voucher=None,
               resourceItem=None, fileName=None,
               location=None, src=None,
               metadata=None, permissions=None,
               thumbnailhandle=None, thumbnailLocation=None):
        """Upload a file to ACS4.

        Keyword arguments:
        filehandle - Handle to file to be packaged.

        dataPath - Path ON SERVER to file to be packaged.  When this is
            supplied, filehandle should be None.

        resource - Resource id.  (for replace - NYI.)

        voucher - Voucher ID for GBLink.

        resourceItem - Resource item index (for multi-part items.)

        fileName - File name to use for packaged resource

        location - Path ON SERVER (or ftp url) where encrypted results
            should be placed.

        src - HTTP url that ACS4 will say the resource can be
            downloaded from.

        permissions - This should be xml describing the item
            permissions, if any.  The best way to get this is to
            configure a sample book in the ACS4 admin console UI, then
            copy it here.  Any valid ACS4 xml fragment that includes a
            'permissions' element should work.  A permissions sub-dict
            as returned by other calls will also work.

        metadata - Similar to permissions.  A flat name : value dict
            is also accepted.  ACS4 will fill in missing values from
            the media.  Metadata fields should be less than 128 chars.

        thumbnailhandle - a filehandle to a thumbnail image

        thumbnailLocation - Path on server (or ftp url) where
            thumbnail will be placed

        """
        if filehandle is None and dataPath is None:
            raise Acs4Exception('upload: please supply fileHandle or dataPath')
        if filehandle is not None and dataPath is not None:
            raise Acs4Exception('upload: both filehandle and dataPath supplied')

        el = etree.Element('package', nsmap={None: AdeptNS})

        if filehandle is not None:
            etree.SubElement(el, 'data').text = \
                base64.encodestring(filehandle.read())
        else:
            etree.SubElement(el, 'dataPath').text = dataPath

        if resource is not None:
            etree.SubElement(el, 'resource').text = resource
        if voucher is not None:
            etree.SubElement(el, 'voucher').text = voucher
        if resourceItem is not None:
            etree.SubElement(el, 'resourceItem').text = resourceItem
        if fileName is not None:
            etree.SubElement(el, 'fileName').text = fileName
        if location is not None:
            etree.SubElement(el, 'location').text = location
        if src is not None:
            etree.SubElement(el, 'src').text = src

        if thumbnailhandle is not None:
            etree.SubElement(el, 'thumbnailData').text = \
                base64.encodestring(thumbnailhandle.read())

        if thumbnailLocation is not None:
            etree.SubElement(el, 'thumbnailLocation').text = thumbnailLocation

        if permissions is not None:
            if isinstance(permissions, dict):
                perms_el = o_to_el(permissions, 'permissions')
            else:
                perms_el = read_xml(permissions, 'permissions')
            el.append(perms_el)
        if metadata is not None:
            if isinstance(metadata, dict):
                meta_el = o_to_meta_el(metadata)
            else:
                meta_el = read_xml(metadata, 'metadata')
            el.append(meta_el)

        signed_request = add_hmac_envelope(el, self.password)
        response = post(signed_request, self.host, self.port,
                        '/packaging/Package')
        if response is None:
            return None
        return el_to_o(response)


    # XXX just add an object request_args to this?
    def queryresourceitems(self, start=0, count=10, distributor=None,
                           sharedSecret=None):
        el = etree.Element('request', nsmap={None: AdeptNS})
        if distributor is not None:
            etree.SubElement(el, 'distributor').text = distributor;
        if sharedSecret is not None:
            etree.SubElement(el, 'sharedSecret').text = sharedSecret;
        add_limit_el(el, start, count)
        etree.SubElement(el, 'QueryResourceItems')
        signed_request = add_hmac_envelope(el, self.password)
        response = post(signed_request, self.host, self.port,
                        '/admin/QueryResourceItems')
        if response is None:
            return None
        return [el_to_o(info_el) for info_el in
                response.findall('.//' + AdeptNSBracketed + 'resourceItemInfo')]

    # below are 'derived actions - shortcuts'
    # XXX abstract with decorator?
    def get_distributor_info(self, distributor=None):
        if distributor is None:
            distributor = self.distributor # might also be None
        request_args = { 'distributor': distributor }
        reply = self.request('Distributor', 'get', request_args)
        # this could return list!  Is that an impedance mismatch?
        return reply[0]

    def get_distributors(self):
        return self.request('Distributor', 'get')

    def get_resourcekey_info(self, resource):
        """ Get a dict of information describing a resource.

        This is where permissions are handled in the ACS4 database.

        Note that this is in the 'operator inventory', not as assigned to
        a specific distributor.

        The resource permissions are not recursively parsed, but are
        returned as a string.

        """
        request_args = { 'resource': resource }
        reply = self.request('ResourceKey', 'get', request_args)
        return reply[0]

    def set_resourcekey_info(self, info):
        """ Set information for a resource, given a dict describing it.

        The resource_info argument should be an object as returned from
        get_resourcekey_info().

        """
        reply = self.request('ResourceKey', 'update', info)
        return reply[0]


    def get_resourceitem_info(self, resource):
        # handle multiples?
        request_args = { 'resource': resource }
        reply = self.request('ResourceItem', 'get')
        return reply[0]


    def set_resourceitem_info(self, info):
        """ note that acs4 won't let this change metadata info """

        reply = self.request('ResourceItem', 'update', info)
        return reply[0]


if __name__ == '__main__':
    raise Exception('not to be called as a __main__')
