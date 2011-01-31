import acs4

acs4.debug = True

c = acs4.ContentServer('your.server.here', 8080, 'your_password_here')
c.queryresourceitems(count=3, start=2)
c.get_distributor_info()

c.queryresourceitems()
testbook_fh = open('sample.epub')

testbook_info = c.upload(testbook_fh, metadata={ 'identifier':'testbook' })

dists = c.request('Distributor', 'get', {})
testdist = dists[2]

c.request('DistributionRights', 'create', { 'distributor': testdist['distributor'], 'resource': testbook_info['resource'], 'distributionType':'loan', 'returnable':'true', 'available':'1'} )

c.mint(testbook_info['resource'], ordersource='foo store', shared_secret=testdist['sharedSecret'])

