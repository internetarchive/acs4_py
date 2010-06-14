#!/usr/bin/env python

"""
Copyright(c)2010 Internet Archive. Software license AGPL version 3.

This file is part of bookserver.

    bookserver is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    bookserver is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License
    along with bookserver.  If not, see <http://www.gnu.org/licenses/>.

    The bookserver source is hosted at http://github.com/internetarchive/bookserver/
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

AdeptNS = 'http://ns.adobe.com/adept'
default_dist = 'urn:uuid:00000000-0000-0000-0000-000000000001'
nonce = None

"""
python ../acs4.py --password='' --debug --action=upload ia331529.us.archive.org ../logofcowboynarra00adamuoft.epub
python ../acs4.py --password='' --debug --action=queryresourceitems ia331529.us.archive.org urn:uuid:00000000-0000-0000-0000-000000000001


--action=request --resource=(some book) --distributor=(iadistrutor) --distributionType=buy $SERVER DistributionRights create

"""


def main(argv):
    import optparse

    parser = optparse.OptionParser(usage='usage: %prog [options] server_url content_filename',
                                   version='%prog 0.1',
                                   description='Upload a file to ACS.')
    parser.add_option('-p', '--password',
                      action='store',
                      help='ACS password')
    parser.add_option('-d', '--debug',
                      action='store_true',
                      help='Print debugging output')
    parser.add_option("--action", action="store", choices=['queryresourceitems',
                                                           'request',
                                                           'upload'],
                      help='ACS action to perform')

    # also repeat these below, near 'dyno'
    request_arg_names = ['distributor',
                         'resource',
                         'distributionType'
                         ]
    for name in request_arg_names:
        parser.add_option('--' + name,
                          action='store',
                          help=name + ' argument for request')

    opts, args = parser.parse_args(argv)

    # XXX make action naked 1rst arg

    if not opts.password:
        parser.error("We think a password arg might be required")
    if not opts.action:
        parser.error("Please specify an action");

    if opts.action.lower() == 'queryresourceitems':
        queryresourceitems(args[0], args[1], opts.password, opts.debug)
    if opts.action.lower() == 'request':
        if len(args) is not 3:
            parser.error("For 'request' action, please supply 3 args: server, api, action")
        if not args[2] in ['get', 'count', 'create', 'delete', 'update']:
            parser.error('action must be get count create delete update')
        print opts
        request_args = {}
        
        # from  pydbgr.api import debug
        # debug()
        
        # TODO make this dyno, per below.  But opts is an
        # optparse.Values, and doesn't have __getitem__!
        # request_args = dict([(name, opts[name]) for name in request_arg_names])

        request_args['distributor'] = opts.distributor
        request_args['resource'] = opts.resource
        request_args['distributionType'] = opts.distributionType

        request(args[0], args[1], args[2], request_args, opts.password, opts.debug)
    elif opts.action == 'upload':
        if len(args) != 2:
            parser.error("For 'upload' action, please supply 2 arguments: server and filename")
        upload(args[0], args[1], opts.password, opts.debug)
    parser.destroy()


def request(server, api, action, request_args, password, debug):
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="no"?>' +
        '<request action="' + action + '" xmlns="http://ns.adobe.com/adept"/>')

    print xml
    tree = etree.parse(StringIO(xml))
    root_el = tree.getroot()
    add_envelope(root_el, password, debug=debug)
    api_el = etree.SubElement(root_el, api[0].lower() + api[1:])

    for key in request_args.keys():
        etree.SubElement(api_el, key).text = request_args[key]
    
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
