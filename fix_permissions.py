#!/usr/bin/env python

# This code demonstrates 'fixing' permissions for every resource
# managed by an ACS system.

# It lists every resource, then:
# Sets the base permissions to an open setting
# If that resource is available through a specified distributor, then:
# Sets the permissions associated with distributing the book to a specific set, and
# Modifies the available number of copies.

import sys
import acs4
import json

distributor = 'urn:uuid:YOUR_DISTRIBUTOR_ID_HERE'
c = acs4.ContentServer('YOUR.SERVER.ORG', 80, 'YOUR.PASSWORD')


def main(args):
    limit = None

    for i, ri in enumerate(c.get_resourceitem_iterator()):
        if limit is not None and i >= limit:
            break
        if i % 100 == 0:
            print >> sys.stderr, i
        fixperms(ri['resource'])


def fixperms(resource):
    rkey_info = c.request('ResourceKey', 'get', { 'resource' : resource })
    if rkey_info is None or len(rkey_info) == 0:
        return
    # print json.dumps(rkey_info, indent=4)
    rkey_info = rkey_info[0]
    rkey_info['permissions'] = { 'display': None,
                                 'excerpt': None,
                                 'print': None }
    c.request('ResourceKey', 'update', rkey_info)
    dist_info = c.request('DistributionRights', 'get', {'resource': resource,
                                                        'distributor': distributor})
    if dist_info is not None and len(dist_info) != 0:
        # print json.dumps(dist_info, indent=4)
        dist_info = dist_info[0]
        dist_info['permissions'] =  {'display': {'duration': '1209600'}}
        dist_info['available'] = '49999'
        c.request('DistributionRights', 'update', dist_info)


if __name__ == '__main__':
    args = sys.argv[1:]
    main(args)
