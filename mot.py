#!/usr/bin/env python3

import sys, getopt, json, time, threading, queue, os, urllib.request, urllib.parse

# for debug:
import http.client
http.client.HTTPConnection.debuglevel = 1

config_file = '/etc/mot.conf'
config = { 'service': {}, 'sensors': [] }

# Template for sensor handlers:
#
# def handler(name, send_queue, <arguments from config>, **kwargs):
#	<initialize>
#	while True:
#		<read sensor value>
#		send_queue.put(<received value>)
#		<wait for a bit>

# Reads first line of each given file, and reports them in same order as sensor fields are specified.
# - files: array of file names
# - poll_interval: amount of seconds to wait between reads
# - report_unchanged: if true, will report every reading, even if it's exactly same as previous reading
#
def file_poll_handler(sensor, send_queue, files, poll_interval, report_unchanged, **kwargs):
	last_result = None
	print("started file_poll sensor")
	while True:
		result = [ open(f).readline().strip() for f in files ]
		print("got", result)
		if bool(int(report_unchanged)) or result != last_result:
			send_queue.put(result)
			last_result = result
		time.sleep(int(poll_interval))

def get_auth():
	return {
		'DriverManagerId': config['service']['id'],
		'DriverManagerPassword': config['service']['password']
	}

def get_location():
	try:
		# if device config hardcodes location, return that
		return config['device']['location']
	except KeyError:
		try:
			# implement some GPS/WiFi geolocation API call
			return None
		except:
			return None

def call(func, data):
	# make a HTTP POST request with UTG-8 encoded JSON data and return response object
	url = urllib.parse.urljoin(config['service']['base_url'], func)
	r = urllib.request.Request(url)
	r.add_header('Content-Type', 'application/json;charset=utf-8')
	data = json.dumps(data, indent=4)
	return urllib.request.urlopen(r, data.encode())


def walk(o, func):
	if isinstance(o, dict):
		return { k: walk(v, func) for k, v in o.items() }
	elif isinstance(o, list):
		return [ walk(i, func) for i in o ]
	else:
		return func(o)

def expand_macros(s):
	if isinstance(s, str) and len(s) > 0:
		if s[0] == '@':
			f = s[1:]
			if os.path.exists(f):
				return open(f).read().strip()
	return s


def register_sensor(s):
	# construct message from sensor configuration and device/location specific data
	data = {
		'Auth': get_auth(),
		'Package': s['registration_package']
	}
	details = data['Package']['SensorDetails']
	details['DriverManagerId'] = config['service']['id']
	loc = get_location()
	if loc:
		details.update(loc)
	data = walk(data, expand_macros)

	# call the HTTP API
	r = call('RegisterSensor', data)
	if r.status == 200:
		s['id'] = json.loads(r.read())
		print('ID:', s['id'])
	else:
		raise RuntimeError(r.read())
	return s

def post_sensor_data(s, readings):
	# construct message
	fields = [ f['ReadingName'] for f in sensor['registration_package']['SensorFields'] ]
	data = {
		'Auth': get_auth(),
		'Package': {
			'SensorInfo': {
				'SensorId': s['id']
			},
			'SensorData': dict.fromkeys(fields, readings),
		}
	}

	# call the HTTP API
	r = call('PostSensorData', data)
	if r.status != 200:
		raise RuntimeError(r.read())
	print("Success")


def main():
	global config_file, config

	# parse command line parameters
	try:
		optlist, args = getopt.getopt(sys.argv[1:], 'c:')
	except getopt.GetoptError as err:
		print(err)
		print("\nUsage: %s [options]" % sys.argv[0])
		print("Options:")
		print("\t-c <config file>\tUse specified config file instead of %s" % config_file)
		sys.exit(1)
	for o, a in optlist:
		if o == '-c':
			config_file = a

	# read and parse configuration file
	try:
		config = json.load(open(config_file))
		sensors = map(register_sensor, config['sensors'])
	except (FileNotFoundError, ValueError) as err:
		print(config_file, ':', err)
		sys.exit(1)
	except RuntimerError as err:
		print("Could not register sensor:", err)
		sys.exit(1)

	# start each sensor monitor in its own thread
	send_queue = queue.Queue()
	handlers = {
		'file-poll': file_poll_handler
	}
	for s in sensors:
		t = threading.Thread(target = hanlders[s['type']],
				     args = (s, send_queue),
				     kwargs = s, daemon = True)
		s['thread'] = t
		t.start()

	# wait for incoming values form sensors, and send them upstream
	try:
		while True:
			event = send_queue.get()
			print("SENDING", event)
			post_sensor_data(event)
	except KeyboardInterrupt:
		pass

if __name__ == '__main__':
	main()

