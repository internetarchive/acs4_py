import acs4

acs4.debug = True

# create the server object
c = acs4.ContentServer('your.server.here', 8080, 'your_password_here')

# list a few already_loaded resources
c.queryresourceitems(start=2 count=4)

# query existing distributors
c.get_distributor_info()

# make a new distributor...
# make a shared secret to use with the new dist (specific format seems needed.)
ss = acs4.make_secret()
newdist = 
c.request('Distributor', 'create', { 'name':'testdist',
                                     'description':'test distributor',
                                     'sharedSecret':ss
                                     'distributorURL':'http://sample.com',
                                     'notifyURL':'http://sample.com/notify.py',
                                     'linkExpiration':120,
                                     'maxLoanCount':3 } )
# returns json description of dist, matching supplied request args,
# with added newdist['distributor'] is now the new distributor ID

# Update values:
newdist['maxLoanCount'] = 7
newdist['notifyURL'] = 'http://sample.com/acs4_notify.py'
c.request('Distributor', 'update', newdist)


# XXX example of looking up by dist name from list?
# XXX example of deleting?
c.request('Distributor', 'delete', newdist['distributor'])
# returns <response><deleted>true</deleted></response> --> []
           
        


testbook_fh = open('sample.epub')

testbook_info = c.upload(testbook_fh, metadata={ 'identifier':'testbook' })

# better to use this, as the license info in the original returned struct
# seems to muck things up
testbook_info = c.request('ResourceItem', 'get',
                          { 'resource':testbook_info['resource'] })

# then we can modify the obj, and use it to make updates: it's best to
# use a fully populated object like this, as unspecified values in
# update get wiped from the db.
testbook_info['src'] = 'http://new_url_for_resource'
testbook_info = c.request('ResourceItem', 'update', testbook_info)


# deleting it after it's just been created:
c.request('ResourceItem', 'delete', { 'resource':info['resource'],
                                      'resourceItem':info['resourceItem'] } )
# NOTE that this doesn't appear to delete the file?

dists = c.request('Distributor', 'get', {})
testdist = dists[2]

c.request('DistributionRights', 'create',
          { 'distributor': testdist['distributor'],
            'resource': testbook_info['resource'],
            'distributionType':'loan',
            'returnable':'true', 'available':'1'} )

# to undo this:
# c.request('DistributionRights', 'delete',
#           { 'distributor': testdist['distributor'],
#             'resource': testbook_info['resource'] } )


# Get resources for a specific distributor:
# XXX requires bogus hack, as this api
c.request('ResourceItem', 'get', { 'distributor':testdist['distributor'] },
          use_request_args_el=False)


# ordersource required if shared_secret used
c.mint(testbook_info['resource'], ordersource='foo store', shared_secret=testdist['sharedSecret'])
