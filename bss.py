#!/usr/bin/env python

#import cgitb; cgitb.enable()
import sys

import web
import json

import warnings
warnings.filterwarnings("ignore", message="the sets module is deprecated")
import MySQLdb

import uuid


#def cgidebugerror():
#    """                                                                         
#    """
#    _wrappedstdout = sys.stdout
#    sys.stdout = web._oldstdout
#    cgitb.handler()
#    sys.stdout = _wrappedstdout
#
#web.internalerror = cgidebugerror



urls = (
  '/is_loaned_out/?(.*)', 'is_loaned_out',
  '/fulfillment_info/?(.*)', 'fulfillment_info',
  '/resource_info_by_id/?(.*)', 'resource_info_by_id', # must precede below
  '/resource_info/?(.*)', 'resource_info',
  '/transaction_info/?(.*)', 'transaction_info',
  '/item/(.*)', 'item',
)

app = web.application(urls, globals())

dbschema = """ 

mysql> show databases;
+--------------------+
| Database           |
+--------------------+
| information_schema |
| adept              |
| mysql              |
+--------------------+
3 rows in set (0.00 sec)

mysql> use adept;
Reading table information for completion of table and column names
You can turn off this feature to get a quicker startup with -A

Database changed
mysql> show tables;
+--------------------+
| Tables_in_adept    |
+--------------------+
| distributionrights |
| distributor        |
| distusednonce      |
| fulfillment        |
| fulfillmentitem    |
| license            |
| licensecertificate |
| resourceitem       |
| resourcekey        |
| schemaversion      |
| secondaryresource  |
| userpublic         |
| userusednonce      |
+--------------------+
13 rows in set (0.00 sec)

mysql> describe fulfillment;
+---------------+--------------+------+-----+---------+-------+
| Field         | Type         | Null | Key | Default | Extra |
+---------------+--------------+------+-----+---------+-------+
| fulfillmentid | binary(20)   | NO   | PRI | NULL    |       |
| distid        | binary(16)   | NO   | MUL | NULL    |       |
| transid       | varchar(127) | NO   | MUL | NULL    |       |
| transtime     | datetime     | NO   |     | NULL    |       |
| signref       | binary(20)   | NO   | MUL | NULL    |       |
| loanuntil     | datetime     | YES  |     | NULL    |       |
| userid        | binary(16)   | NO   | MUL | NULL    |       |
| confirmed     | char(1)      | YES  |     | NULL    |       |
| returnable    | char(1)      | YES  |     | NULL    |       |
| returned      | char(1)      | YES  |     | NULL    |       |
+---------------+--------------+------+-----+---------+-------+
10 rows in set (0.00 sec)

mysql> describe fulfillmentitem;
+---------------+------------+------+-----+---------+-------+
| Field         | Type       | Null | Key | Default | Extra |
+---------------+------------+------+-----+---------+-------+
| fulfillmentid | binary(20) | NO   | MUL | NULL    |       |
| resourceid    | binary(16) | NO   | MUL | NULL    |       |
| until         | datetime   | YES  |     | NULL    |       |
| permissions   | blob       | YES  |     | NULL    |       |
+---------------+------------+------+-----+---------+-------+
4 rows in set (0.00 sec)

mysql> Bye
"""

class acs4db():

    def __init__(self):
        pass

    def connect(self):
        host = '127.0.0.1'
        db = 'adept'
        user = 'root'
        pw_file = open('/usr/local/bss/db-password', 'r')
        passwd = pw_file.readline().rstrip("\n")

        # retry the connect because mysql server at IA sometimes causes this
        # exception:
        # OperationalError: (2013,
        #     "Lost connection to MySQL server at 'reading authorization packet',system error: 0")
        #
        # this appears to be related to a config problem with mysqld and a loaded web server.
        # see: http://bugs.mysql.com/bug.php?id=28359

        try_count = 1
        max_tries = 5
        self.conn = None
        while (not self.conn) and (try_count <= max_tries):
            try:
                try_count = try_count + 1
                self.conn =  MySQLdb.connect(
                    host=host,
                    db=db,
                    user=user,
                    passwd=passwd,
                    )
            except MySQLdb.OperationalError, e:
                if try_count > max_tries:
                    raise e
        self.conn.set_character_set('utf8')

    def close(self):
        self.conn.close()


    def get_fulfillment_info(self, resource=None):
        """ returns a list of resources in the fulfilment table , values set to dict of handy facts """
        
        resources = [] 
        
        if resource == '':
            resource = None

        self.connect()
        c = self.conn.cursor()
        sql = """
            SELECT DISTINCT resourceid, returned, until, loanuntil FROM fulfillmentitem, fulfillment
                WHERE fulfillmentitem.fulfillmentid = fulfillment.fulfillmentid
        """

        if resource:
            resource_uuid = uuid.UUID(resource)
            c.execute(sql + " AND fulfillmentitem.resourceid = %s ORDER BY loanuntil DESC", (resource_uuid.bytes, ))
        else:
            c.execute(sql + " ORDER BY loanuntil DESC")

        r = c.fetchone()
        while r != None:
            r_dict = {}
            r_dict['resourceid'] = 'urn:uuid:' + str(uuid.UUID(bytes=r[0]))
            r_dict['returned'] = r[1]
            if r[2]:
                r_dict['until'] = r[2].isoformat()
            else:
                r_dict['until'] = None
            if r[3]:
                r_dict['loanuntil'] = r[3].isoformat()
            else:
                r_dict['loanuntil'] = None
            resources.append(r_dict)
            r = c.fetchone()

        return resources


    def get_loaned_out(self, resource=None):
        """ returns a list of unloanable books (someone else has 'em) according to acs"""
        resources = [] 
        
        if resource == '':
            resource = None

        self.connect()
        c = self.conn.cursor()
        sql = """
            SELECT DISTINCT resourceid, returned, until, loanuntil, transtime, transid FROM fulfillmentitem, fulfillment
                WHERE fulfillmentitem.fulfillmentid = fulfillment.fulfillmentid
                    AND (
                            (
                                (loanuntil IS NULL OR until IS NULL)
                                OR
                                (loanuntil > NOW()) 
                            )
                            AND 
                            ( returned IS NULL OR returned = 'F')
                        )
        """

        if resource:
            resource_uuid = uuid.UUID(resource)
            c.execute(sql + " AND fulfillmentitem.resourceid = %s ORDER BY loanuntil DESC", (resource_uuid.bytes, ))
        else:
            c.execute(sql + " ORDER BY loanuntil DESC")

        r = c.fetchone()
        while r != None:
            r_dict = {}
            r_dict['resourceid'] = 'urn:uuid:' + str(uuid.UUID(bytes=r[0]))
            r_dict['transtime'] = r[-2].isoformat()
            r_dict['transid'] = r[-1]
            r_dict['returned'] = r[1]
            if r[2]:
                r_dict['until'] = r[2].isoformat()
            else:
                r_dict['until'] = None
            if r[3]:
                r_dict['loanuntil'] = r[3].isoformat()
            else:
                r_dict['loanuntil'] =  None

            resources.append(r_dict)
            r = c.fetchone()

        return resources

    def _fetchone_dict(self, cursor):
        r = cursor.fetchone()
        d = {}
        if r == None:
            return r
        for i in range(len(r)):
            d[cursor.description[i][0]] = r[i]
            #sys.stderr.write(repr(d[cursor.description[i][0]]) + " = " + repr(r[i]) + "\n")
        return d

    def get_resource_info(self, resource=None):
        """ returns a list of resource entries in the resource table for a given resource """
        resources = []

        if resource == '':
            resource = None

        self.connect()
        c = self.conn.cursor()
        sql = """
            SELECT *
                FROM resourceitem
        """

        if resource:
            resource_uuid = uuid.UUID(resource)
            c.execute(sql + " WHERE resourceid = %s ORDER BY title,resourceid ", (resource_uuid.bytes, ))
        else:
            c.execute(sql + " ORDER BY title,resourceid ")

        r = self._fetchone_dict(c)
        while r != None:
            r['resourceid'] = 'urn:uuid:' + str(uuid.UUID(bytes=r['resourceid']))
            resources.append(r)
            #sys.stderr.write(r['resourceid'] + "\n")
            #json.dumps(r)
            r = self._fetchone_dict(c)
            

        return resources

    def get_resource_info_by_id(self, identifier=None):
        """
        Returns a list of resource entries matching a given
        identifier.  Each resource also includes a 'loanstatus' entry
        (see is_loaned_out) that might be null.

        This depends on the 'identifier' metadata field being set
        appropriately at resource load time.
        """

        resources = []

        if identifier == '' or identifier is None:
            return resources

        self.connect()
        c = self.conn.cursor()

        sql = """
            SELECT *
                FROM resourceitem
                    WHERE identifier = %s
                        ORDER BY format
        """
        c.execute(sql, (identifier, ))

        r = self._fetchone_dict(c)
        while r != None:
            r['resourceid'] = 'urn:uuid:' + str(uuid.UUID(bytes=r['resourceid']))
            loanstatuses = self.get_loaned_out(r['resourceid'])
            if len(loanstatuses) > 0:
                loanstatus = loanstatuses[0]
            else:
                loanstatus = None
            r['loanstatus'] = loanstatus
            resources.append(r)
            r = self._fetchone_dict(c)
        
        return resources

    def get_transaction_info(self, transid):
	sql = ("SELECT ri.identifier, fi.resourceid, f.transid, f.returned, f.transtime, f.loanuntil"  +
	       " FROM fulfillmentitem fi, fulfillment f, resourceitem ri" + 
	       " WHERE ri.resourceid=fi.resourceid and fi.fulfillmentid=f.fulfillmentid and f.transid=%s")

	self.connect()
        c = self.conn.cursor()
        c.execute(sql, (transid, ))
	row = self._fetchone_dict(c)
	if row:
	  row['resourceid'] = 'urn:uuid:' + str(uuid.UUID(bytes=row['resourceid']))
	  row['loanuntil'] = row['loanuntil'].isoformat()
	  row['transtime'] = row['transtime'].isoformat()
        return row

class is_loaned_out:
    def GET(self, resource):
        web.header("Content-Type", 'text/plain')
        db = acs4db()
        return json.dumps(db.get_loaned_out(resource), sort_keys=True, indent=4)

class fulfillment_info:
    def GET(self, resource):
        web.header("Content-Type", 'text/plain')
        db = acs4db()
        return json.dumps(db.get_fulfillment_info(resource), sort_keys=True, indent=4)

class resource_info:
    def GET(self, resource):
        web.header("Content-Type", 'text/plain')
        db = acs4db()
        return json.dumps(db.get_resource_info(resource), sort_keys=True, indent=4)

class resource_info_by_id:
    def GET(self, identifier):
        web.header("Content-Type", 'text/plain')
        db = acs4db()
        return json.dumps(db.get_resource_info_by_id(identifier), sort_keys=True, indent=4)

class transaction_info:
    def GET(self, transid):
        web.header("Content-Type", 'text/plain')
        db = acs4db()
        return json.dumps(db.get_transaction_info(transid), sort_keys=True, indent=4)

class item:
    def GET(self, identifier):
        web.header("Content-Type", 'text/plain')
	db = acs4db()
	d = {
	  "identifier": identifier,
	  "resources": [self.process_resource(db, x) for x in db.get_resource_info_by_id(identifier)]
	}
	return json.dumps(d, sort_keys=True, indent=4)

    def process_resource(self, db, resource):
	d = {}
	for k in ['resourceid', 'src', 'format']:
	  d[k] = resource[k]
	d['loans'] = db.get_loaned_out(d['resourceid'])
	return d

if __name__ == "__main__":
    app.run()

