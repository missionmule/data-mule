########################################################
## Basic Mission to test waypoints, landing and takeoff
## Daniel Carelli, Mission Mule
## Summer 2017
########################################################

from dronekit import connect, VehicleMode, LocationGlobalRelative, LocationGlobal, Command
import time
import math
from pymavlink import mavutil
import argparse

## fn: Callback definition for mode observer
def mode_callback(self, attr_name, msg):
	print "Vehicle Mode", self.mode
	if str(self.mode) == "VehicleMode:STABILIZE": # Quit program entirely to silence Raspberry Pi
		print "Quitting program..."
		exit()
		print "We should never get here! \nFUCK FUCK FUCK \nAHHHH"

## fn: EXTRACT WAYPOINTS AND LANDING SEQUENCE FROM FILE
def extract_waypoints():
    parser = argparse.ArgumentParser(description='Process some.')
    parser.add_argument('file', type=argparse.FileType('r'), nargs='+')
    args = parser.parse_args()

    print "Reading Mission File"
    #  Read absolute GPS coordinates and altitude from CSV file into list of lists
    cameras = [[i for i in line.strip().split(',')] for line in args.file[0].readlines()]

    #  Raw latitude, longitude, and altitude for CAMERA TRAPS translated to
    #  LocationGlobals
    camera_waypoints = []
    for line in range(len(cameras)):
    	if not cameras[line][0].isalpha(): # Not data column descriptor
            camera_waypoints.append(LocationGlobal(float(cameras[line][0]),float(cameras[line][1]),float(cameras[line][2])))
            print "Lon: " + str(cameras[line][0]) + "Lat: " + str(cameras[line][1]) + "Alt: " + str(cameras[line][2])

    print "Reading Landing Sequence"
    #  Read absolute GPS coordinates and altitude from CSV file into list of lists
    landing = [[i for i in line.strip().split(',')] for line in args.file[1].readlines()]

    #  Raw latitude, longitude, and altitude for LANDING SEQUENCE translated to
    #  LocationGlobals
    landing_waypoints = []
    for line in range(len(landing)):
    	if not landing[line][0].isalpha(): # Not data column descriptor
            landing_waypoints.append(LocationGlobal(float(landing[line][0]),float(landing[line][1]),float(landing[line][2])))
            print "Lon: " + str(landing[line][0]) + "Lat: " + str(landing[line][1]) + "Alt: " + str(landing[line][2])

    return camera_waypoints, landing_waypoints

## fn: UPLOAD WAYPOINT
def upload_waypoint(original_location, waypoints):

    print "Download mission"
    download_mission()

    cmds = vehicle.commands

    print "Clear any existing commands"
    cmds.clear()

    print "Download mission"
    download_mission()

    print "Adding new waypoint commands."
    for i in range(len(waypoints)):
        cmds.add(Command( 0, 0, 0, mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT, mavutil.mavlink.MAV_CMD_NAV_WAYPOINT, 0, 0, 0, 0, 0, 0, waypoints[i].lat, waypoints[i].lon, int(waypoints[i].alt)))

    print "Uploading Commands"
    cmds.upload()

## fn: UPLOAD LANDING SEQUENCE
def upload_landing_sequence(waypoints):

    last = len(waypoints)

    print "Download mission"
    download_mission()

    cmds = vehicle.commands

    print "Clear any existing commands"
    cmds.clear()

    print "Download mission"
    download_mission()

    #  Approach runway
    print "Adding runway approach waypoints"
    for i in range(last-1):
        cmds.add(Command( 0, 0, 0, mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT, mavutil.mavlink.MAV_CMD_NAV_WAYPOINT, 0, 0, 0, 0, 0, 0, waypoints[i].lat, waypoints[i].lon, int(waypoints[i].alt)))

    #  Start landing Ssquence
    print "Adding start landing command"
    cmds.add(Command( 0, 0, 0, mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT, mavutil.mavlink.MAV_CMD_DO_LAND_START, 0, 0, 0, 0, 0, 0, 0, 0, 0))

    #  Execute landing operation
    print "Adding landing command"
    cmds.add(Command( 0, 0, 0, mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT, mavutil.mavlink.MAV_CMD_NAV_LAND, 0, 0, 0, 0, 0, 0, waypoints[last].lat, waypoints[last].lon, 0))

    print "Uploading Landing Sequence"
    cmds.upload()

## fn: ARM AND TAKEOFF
def arm_and_takeoff(targerAltitude):

    #  Don't let the user try to arm until autopilot is ready
    print "Basic pre-arm checks"
    while not vehicle.is_armable:
        print " Waiting for vehicle to initialise..."
        time.sleep(1)

    print "Download mission"
    download_mission()

    cmds = vehicle.commands

    print "Clear any existing commands"
    cmds.clear()

    print "Download mission"
    download_mission()

    print "Uploading Takeoff command"
    cmds.add(Command( 0, 0, 0, mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT, mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, 0, 0, 30))
    cmds.upload()

    print "Arming motors"
    # Plane should arm in MANUAL mode
    vehicle.mode = VehicleMode("MANUAL")
    vehicle.armed = True

    vehicle.mode = VehicleMode("AUTO")

    while str(vehicle.mode) != "LOITER":
        print "Takeoff in progress. Altitude: ", vehicle.location.global_relative_frame.alt, " meters"
        time.sleep(0.5)

## CALCULATE DISTANCE BETWEEN TWO GPS COORDINATE
def get_distance_metres(aLocation1, aLocation2):
    """
    Returns the ground distance in metres between two LocationGlobal objects.
    This method is an approximation, and will not be accurate over large distances and close to the
    earth's poles. It comes from the ArduPilot test code:
    https://github.com/diydrones/ardupilot/blob/master/Tools/autotest/common.py
    """
    dlat = aLocation2.lat - aLocation1.lat
    dlong = aLocation2.lon - aLocation1.lon
    return math.sqrt((dlat*dlat) + (dlong*dlong)) * 1.113195e5

## fn: SET UP FULL LOITER AUTOMOATIC MISSION
def set_full_loiter_mission(camera_locations, landing_sequence):
    print "Download mission"
    cmds = vehicle.commands
    cmds.download()
    cmds.wait_ready()

    print "Clear any existing commands"
    cmds.clear()

    #  Add takeoff command
    print "Adding takeoff command"
    cmds.add(Command( 0, 0, 0, mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT, mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, 0, 0, 30))

    #  Add camera trap locations as unlimeted loiter commands. The aircraft will
    #  fly to the GPS coordinate and circle them indefinitely. The autopilot
    #  proceed to the next mission item after vehicle mode is switched out of
    #  AUTO and back into AUTO.
    print "Adding new LOITER waypoint commands."
    for i in range(len(camera_locations)):
        cmds.add(Command( 0, 0, 0, mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT, mavutil.mavlink.MAV_CMD_NAV_LOITER_UNLIM, 0, 0, 0, 0, 10, 0, camera_locations[i].lat, camera_locations[i].lon, int(camera_locations[i].alt)))

    #  Add landing sequence
    print "Adding landing sequece"

    #  Start landing Ssquence
    print "Adding start landing command"
    cmds.add(Command( 0, 0, 0, mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT, mavutil.mavlink.MAV_CMD_DO_LAND_START, 0, 0, 0, 0, 0, 0, 0, 0, 0))

    #  Approach runway
    print "Adding runway approach waypoints"
    for i in range(len(landing_sequence)-1):
        cmds.add(Command( 0, 0, 0, mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT, mavutil.mavlink.MAV_CMD_NAV_WAYPOINT, 0, 0, 0, 0, 0, 0, landing_sequence[i].lat, landing_sequence[i].lon, int(landing_sequence[i].alt)))

    #  Execute landing operation
    print "Adding landing command"
    cmds.add(Command( 0, 0, 0, mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT, mavutil.mavlink.MAV_CMD_NAV_LAND, 0, 0, 0, 0, 0, 0, landing_sequence[len(landing_sequence)-1].lat, landing_sequence[len(landing_sequence)-1].lon, 0))

    #  Upload mission
    print "Uploading full loiter mission"
    cmds.upload()

################  MAIN  ################
## CONNECT TO VEHICLE

connection_string = "/dev/ttyS0"
print 'Connecting to vehicle on: %s' % connection_string
vehicle = connect('/dev/ttyS0', baud=57600, wait_ready=True)

vehicle.add_attribute_listener('mode', mode_callback)

## EXTRACT WAYPOINTS AND LANDING SEQUNCE
camera_locations, landing_sequence = extract_waypoints()

## UPLOAD FULL LOITER MISSION
set_full_loiter_mission(camera_locations, landing_sequence)

## WAIF FOR VEHICLE TO SWITCH TO AUTO
while vehicle.mode.name != "AUTO":
    print "Waiting for user to begin mission"
    time.sleep(1)
## MONITOR PROGRESS ON EACH CAMERA LOCATION
for camera in camera_locations:
    while get_distance_metres(camera, vehicle.location.global_frame) >= 15:
        print "En route to camera..."
    print "Arrived at camera location. Downloading images..."
    time.sleep(150)

    while vehicle.mode.name != "CIRCLE":
        vehicle.mode = VehicleMode("CIRCLE")

    print "Camera download complete. Beginning next mission item."
    while vehicle.mode.name != "AUTO":
        vehicle.mode = VehicleMode("AUTO")

## RETURN TO HOME
#  At this point, it should begin going through the landing sequence points.
print "Starting Landing Sequence"
