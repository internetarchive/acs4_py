"""
Copyright(c)2010 Internet Archive. Software license AGPL version 3.

Entry points - call from command line, or see:
queryresourceitems, upload, request and mint.

"""

import sys
import optparse
import acs4

def main(argv):
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
                      help='xml file of ACS4 perms - for upload and request')
    parser.add_option('--metadata',
                      action='store',
                      help='xml file of resource metadata - for upload.')
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
                      action='store',
                      default=acs4.defaultport,
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
        acs4.debug = True
    if opts.dry_run:
        acs4.dry_run = True

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
        print acs4.queryresourceitems(server, opts.password,
                                      distributor=opts.distributor,
                                      port=opts.port)
    elif action == 'upload':
        fh = None
        if len(args) == 3:
            if opts.datapath is not None:
                parser.error('--datapath (path to remote file)'
                             ' and filename both supplied.')
            fh = open(args[2])
        elif len(args) == 2:
            if opts.datapath is None:
                parser.error('please supply filename or --datapath argument')
        else:
            parser.error('Wrong number of args supplied to upload action')
        print acs4.upload(server, fh, opts.password,
                          datapath=opts.datapath,
                          permissions=opts.permissions,
                          metadata=opts.metadata,
                          port=opts.port)
    elif action == 'request':
        request_types = ['get', 'count', 'create', 'delete', 'update']
        joined = ', '.join(request_types)
        if len(args) != 4:
            parser.error('For "request" action, please supply server,'
                         ' "request", web_api, request_type - where web_api'
                         ' is e.g. DistributionRights, and request_type'
                         ' is one of ' + joined)
        api = args[2]
        request_type = args[3].lower()
        if not request_type in request_types:
            parser.error('Request type should be one of ' + joined)
        request_args = {}
        
        # TODO make this dynamic.  But opts is an optparse.Values, and
        # doesn't have __getitem__!  request_args = dict([(name,
        # opts[name]) for name in request_arg_names])
        request_args = {
            'distributor': opts.distributor,
            'resource': opts.resource,
            'distributionType': opts.distributionType,
            'available': opts.available,
            'returnable': opts.returnable,
            'resourceItem': opts.resourceItem,
            'notifyURL': opts.notifyURL,
            'user': opts.user,
            }
        print acs4.request(server, api, request_type, request_args,
                           opts.password,
                           permissions=opts.permissions,
                           port=opts.port)

    elif action == 'mint':
        if not opts.resource or not opts.distributor:
            parser.error('Please supply --resource= and --distributor='
                         ' arguments for mint')
        distinfo = acs4.get_distributor_info(server, opts.password,
                                             opts.distributor,
                                             port=opts.port)
        secret = distinfo['sharedSecret']
        name = distinfo['name']
        print acs4.mint(server, secret, opts.resource, 'enterloan', name,
                        port=opts.port)
    parser.destroy()


if __name__ == '__main__':
    main(sys.argv[1:])