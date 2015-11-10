#!/usr/bin/env python3

import sys, getopt, json, time, threading, queue, os, urllib.request, urllib.parse

# for debug:
import http.client
http.client.HTTPConnection.debuglevel = 1

config_file = '/etc/mot.conf'
state_file = '/var/cache/mot.cache'
pid_file = None
config = { 'service': {}, 'sensors': [] }
state = { 'registrations': {} }

# Template for sensor handlers:
#
# def handler(name, send_queue, <arguments from config>, **kwargs):
#	<initialize>
#	while True:
#		<read sensor value>
#		send_queue.put([name, <received value>])
#		<wait for a bit>

# Reads first line of each given file, and reports them in same order as sensor fields are specified.
# - files: array of file names
# - poll_interval: amount of seconds to wait between reads
# - report_unchanged: if true, will report every reading, even if it's exactly same as previous reading
#
def file_poll_handler(name, send_queue, files, poll_interval, report_unchanged, **kwargs):
	last_result = None
	print("started file_poll sensor")
	while True:
		result = [ open(f).readline().strip() for f in files ]
		print("got", result)
		if bool(int(report_unchanged)) or result != last_result:
			send_queue.put([name, result])
			last_result = result
		time.sleep(int(poll_interval))

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
			# TODO: implement some GPS/WiFi geolocation API call
			return None
		except:
			return None

def call(func, data):
	# make a HTTP POST request with UTG-8 encoded JSON data and return response object
	url = urllib.parse.urljoin(config['service']['base_url'], func)
	r = urllib.request.Request(url)
	r.add_header('Content-Type', 'application/json;charset=utf-8')
	data = json.dumps(data)
	return urllib.request.urlopen(r, data.encode())

def register_sensor(name, data):
	# construct message from sensor configuration and device/location specific data
	data = {
		'Auth': get_auth(),
		'Package': data['registration_package']
	}
	details = data['Package']['SensorDetails']
	details['DriverManagerId'] = config['service']['id']
	if name in state['registrations']:
		# this is a registration update, rather than new sensor registration
		details['SensorId'] = state['registrations'][name]
	loc = get_location()
	if loc:
		details.update(loc)

	# call the HTTP API
	r = call('RegisterSensor', data)
	if r.status == 200:
		i = json.loads(r.read().decode())
		print('ID:', i)
		return i
	raise RuntimeError(r.read().decode())

def post_sensor_data(name, readings):
	# construct message
	sensor = config['sensors'][name]
	fields = [ f['ReadingName'] for f in sensor['registration_package']['SensorFields'] ]
	data = {
		'Auth': get_auth(),
		'Package': {
			'SensorInfo': {
				'SensorId': state['registrations'][name]
			},
			'SensorData': {
				f: v for f, v in zip(fields, readings)
			}
		}
	}

	# call the HTTP API
	r = call('PostSensorData', data)
	if r.status != 200:
		raise RuntimeError(r.read().decode())
	print("Success")

def save_state():
	# overwrite state file with current state snapshot
	try:
		json.dump(state, open(state_file, 'w'))
	except PermissionError as err:
		print("Could not store state file:", err)
		sys.exit(1)

def show_usage():
	print("Usage: %s [options]" % sys.argv[0])
	print("Options:")
	print("  -h                Show this help")
	print("  -c <config file>  Use specified config file instead of %s" % config_file)
	print("  -s <state file>   Use specified state file to store sensor registrations, instead of %s" % state_file)
	print("  -r                Register sensors according to provided configuration")
	print("  -p <pid file>     Write process id to specified file")

def main():
	global config_file, state_file, config, state, pid_file
	do_registration = False

	# parse command line parameters
	try:
		optlist, args = getopt.getopt(sys.argv[1:], 'c:s:rhp:')
	except getopt.GetoptError as err:
		print(err, "\n")
		show_usage()
		sys.exit(1)
	for o, a in optlist:
		if o == '-c':
			config_file = a
		elif o == '-s':
			state_file = a
		elif o == '-r':
			do_registration = True
		elif o == '-h':
			show_usage()
			sys.exit(0)
		elif o == '-p':
			pid_file = a

	# write PID file if requested
	if pid_file:
		try:
			open(pid_file, 'w').write(str(os.getpgid(0)))
		except IOError as err:
			print("Could not write PID into", pid_file, ':', err)
			sys.exit(1)

	# read and parse configuration file
	try:
		config = json.load(open(config_file))
		config = walk(config, expand_macros)
	except (FileNotFoundError, ValueError) as err:
		print(config_file, ':', err)
		sys.exit(1)

	# attempt to read existing sensor registrations
	try:
		state = json.load(open(state_file))
	except FileNotFoundError as err:
		if not do_registration:
			print("Could not read state file:", err)
			sys.exit(1)

	# either register sensors and quit, or read existing registrations etc. state data
	if do_registration:
		try:
			for name, data in config['sensors'].items():
				state['registrations'][name] = register_sensor(name, data)
			save_state()
		except RuntimeError as err:
			print("Could not register sensor:", err)
			sys.exit(1)
		print(len(state['registrations']), "sensor(s) registered successfully")


	# start each sensor monitor in its own thread
	send_queue = queue.Queue()
	handlers = {
		'file-poll': file_poll_handler
	}
	for name, data in config['sensors'].items():
		t = threading.Thread(target = handlers[data['type']],
				     args = (name, send_queue),
				     kwargs = data, daemon = True)
		t.start()

	# wait for incoming values form sensors, and send them upstream
	try:
		while True:
			name, readings = send_queue.get()
			print("SENSOR:", name, 'READINGS:', readings)
			post_sensor_data(name, readings)
	except KeyboardInterrupt:
		pass

if __name__ == '__main__':
	main()

