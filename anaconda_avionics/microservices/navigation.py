import math
import os
import time
import threading
import logging

from pymavlink import mavutil
from dronekit import connect, VehicleMode, Command

from anaconda_avionics.microservices import Download
from anaconda_avionics.utilities import XBee

class Navigation(object):

    # -----------------------
    # Constants
    # -----------------------

    # TODO: grab these constants from those set on vehicle itself via QGroundControl parameter setup
    AIRSPEED_SLOW = 10
    AIRSPEED_MED = 13
    AIRSPEED_FAST = 16

    OVERALL_DOWNLOAD_TIMEOUT_SECONDS = 60
    DOWNLOAD_CONNECTION_TIMEOUT_SECONDS = 20
    DOWNLOAD_READ_WRITE_TIMEOUT_SECONDS = 20

    # -----------------------
    # Private variables
    # -----------------------

    __xbee = None                   # XBee comm module
    __vehicle = None                # Dronekit vehicle reference

    __data_stations_queue = None    # Queue of data stations to be visited
    __landing_waypoints = None      # Queue of landing waypoints to be visited on landing approach


    # -----------------------
    # Public variables
    # -----------------------

    isNavigationComplete = False    # Allow Mission class to know when navigation has finished

    # -----------------------
    # Set up
    # -----------------------

    def __init__(self, _data_stations_queue, _landing_waypoints):
        self.__data_stations_queue = _data_stations_queue
        self.__landing_waypoints = _landing_waypoints

        # Create connection to XBee module
        self.__xbee = XBee()  # Create and connect to xBee module


    # -----------------------
    # General utility methods
    # -----------------------

    # TODO: rework for less nuclear option--no os.exit(0)
    def mode_callback(self, vehicle, attr_name, msg):
         """
            This function monitors the vehicle mode. If the vehicle is switched to STABALIZE, the companion computer
            (Raspberry Pi) immediately relinquishes control to drone operator for manual operation.
         """
         logging.info("Mode engaged: [%s]" % (str(vehicle.mode.name)))

         if str(vehicle.mode.name) == "STABILIZE":  # Quit program entirely to silence Raspberry Pi
             logging.critical("Killing program and relinquishing control to flight operator.")
             os._exit(0)  # pylint: disable=protected-access
             #  We should never ever ever get here!
             logging.critical("FUCK FUCK FUCK The program should've stopped running.")

    # TODO: There must be a better way to do this... See: Vincenty's formulae (GeoPy package)
    def get_distance_meters(self, location_1, location_2):
        """
            Calculate distance between two GPS coordinates

            Returns the ground distance in metres between two LocationGlobal objects.
            This method is an approximation, and will not be accurate over large distances and close to the
            earth's poles. It comes from the ArduPilot test code:
            https://github.com/diydrones/ardupilot/blob/master/Tools/autotest/common.py
        """
        dlat = location_2.lat - location_1.lat
        dlong = location_2.lon - location_1.lon
        return math.sqrt((dlat * dlat) + (dlong * dlong)) * 1.113195e5


    # -----------------------
    # Mission preparation
    # -----------------------

    def connectToAutopilot(self):
        """
        Connect companion computer to Pixhawk autopilot
        :return:
        """
        # Set up connection with Pixhawk autopilot
        if not "DEVELOPMENT" in os.environ: # When not in development mode, connect to real Pixhawk
            connection_string = "/dev/ttyS0"
        else:  # in development mode, connect to plane over SITL (tcp:127.0.0.1:5760) udp:127.0.0.1:14550
            connection_string = "udp:127.0.0.1:14550"

        logging.debug('Connecting to vehicle on: %s' % connection_string)

        while True:
            try:
                self.__vehicle = connect(connection_string, baud=57600, wait_ready=True)
                break
            except:
                logging.error("Failed to connect to vehicle. Retrying connection...")

        logging.info('Connection to vehicle successful')

    def uploadMission(self, vehicle, data_stations_queue, landing_waypoints):
        """
        Uploads route that the drone will take to service the requested camera traps
        as a series of MAVLink commands to the autopilot.
        """

        cmds = vehicle.commands

        logging.info("Downloading mission...")
        cmds.download()
        cmds.wait_ready()

        logging.info("Clearing existing commands on autopilot...")
        cmds.clear()

        #  Add takeoff command
        logging.info("Adding takeoff command...")
        cmds.add(Command(0,
                         0,
                         0,
                         mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                         mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                         0,
                         0,
                         30,
                         0,
                         0,
                         0,
                         0,
                         0,
                         30))

        #  Add camera trap locations as unlimited loiter commands. The aircraft will
        #  fly to the GPS coordinate and circle them indefinitely. The autopilot
        #  proceeds to the next mission item after vehicle mode is switched out of
        #  AUTO and back into AUTO.
        logging.info("Adding new waypoint commands...")

        cameras = list(data_stations_queue)

        for cam in cameras:
            logging.info('New Camera:\n%s' % cam.summary())
            cmds.add(Command(0,
                             0,
                             0,
                             mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                             mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                             0,
                             0,
                             0,
                             0,
                             0,
                             0,
                             cam.lat,
                             cam.lon,
                             cam.alt))

        # TODO: Use landing sequence from QGroundControl (loiter to altitude then land)
        # See: https://github.com/mavlink/qgroundcontrol/blob/0aad76c5994535b5d552352e3a238f6842ae61c1/src/MissionManager/FixedWingLandingComplexItem.cc lines 200-242

        # Add landing sequence
        logging.info("Adding landing sequence...")

        #  Start landing Sequence
        logging.info("Adding start landing command...")
        cmds.add(Command(0,
                         0,
                         0,
                         mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                         mavutil.mavlink.MAV_CMD_DO_LAND_START,
                         0,
                         0,
                         0,
                         0,
                         0,
                         0,
                         0,
                         0,
                         0))

        # Loiter
        logging.info("Adding landing loiter waypoint...")
        loiter = landing_waypoints[0]
        logging.info('Landing Loiter Waypoint:\n%s' % loiter.summary())
        cmds.add(Command(0,
                         0,
                         0,
                         mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                         mavutil.mavlink.MAV_CMD_NAV_LOITER_TO_ALT,
                         0,
                         0,
                         1,
                         75,
                         0,
                         1,
                         loiter.lat,
                         loiter.lon,
                         loiter.alt))

        # #  Approach runway
        # landing = landing_waypoints.pop()
        # logging.info("Adding runway approach waypoints...")
        # for waypoint in landing_waypoints:
        #     logging.info('New Waypoint:\n%s' % waypoint.summary())
        #     cmds.add(Command(0,
        #                      0,
        #                      0,
        #                      mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
        #                      mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
        #                      0,
        #                      0,
        #                      0,
        #                      0,
        #                      0,
        #                      0,
        #                      waypoint.lat,
        #                      waypoint.lon,
        #                      waypoint.alt))

        # Execute landing operation
        logging.info("Adding landing command...")

        landing = landing_waypoints[1]
        logging.info('Landing Target:\n%s' % landing.summary())
        cmds.add(Command(0,
                         0,
                         0,
                         mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                         mavutil.mavlink.MAV_CMD_NAV_LAND,
                         0,
                         0,
                         0,
                         0,
                         0,
                         0,
                         landing.lat,
                         landing.lon,
                         0))

        #  Upload mission
        logging.info("Uploading full loiter mission...")

        cmds.upload()
        cmds.wait_ready()

        logging.info("Mission upload successful")


    # -----------------------
    # Mission execution
    # -----------------------

    def start(self):
        """
            1) Connect to Pixhawk autopilot
            2) Upload mission
            3) Wait for user to begin mission
            4) Monitor take-off
            5) Set plane to LOITER when arrived at camera trap until download complete
            6) Set plane to AUTO if:
                a) timeout event
                b) camera finishes downloading
            7) Monitor landing
        """

        # Connect companion computer to the drone
        self.connectToAutopilot()

        # Translate data station and landing waypoints into MAVLink mission
        self.uploadMission(self.__vehicle, self.__data_stations_queue, self.__landing_waypoints)

        # Add listener for vehicle mode change
        self.__vehicle.add_attribute_listener('mode', self.mode_callback)

        # Wait for vehicle to be switched to AUTO mode to begin autonomous mission
        logging.info("Waiting for user to begin mission...")
        while str(self.__vehicle.mode.name) != "AUTO":
            logging.debug("Waiting for user to begin mission...")
            time.sleep(1)

        logging.info("Mission starting...")

        cam_num = len(self.__data_stations_queue)

        # Monitor takeoff progress
        logging.info("Taking off...")
        while self.__vehicle.commands.next == 1:
            current_altitude = self.__vehicle.location.global_relative_frame.alt
            logging.debug("Taking off: Current altitude: %s" % current_altitude)
            time.sleep(0.5)

        next_waypoint = self.__vehicle.commands.next

        # Monitor mission progress and engage loiter when each camera trap is reached
        while self.__vehicle.commands.next <= cam_num + 1:

            # Pop reference to data station being approached
            current_data_station = self.__data_stations_queue.popleft()

            logging.info("En route to data station %s..." % (current_data_station.identity))

            # Broadcast request for data station to turn on while en route
            # TODO: uncomment this when XBee class is rewritten to not block
            # self.__xbee.sendCommand('POWER_ON', identity=current_data_station.identity, timeout=6)

            # While en route to the next data station monitor distance
            while self.__vehicle.commands.next == next_waypoint:

                # data_stations are indexed at 0, and commands are indexed at 1
                # with the first reserved for takeoff. This is why we do [next_waypoint-2]
                distance = self.get_distance_meters(current_data_station,
                                                    self.__vehicle.location.global_frame)

                logging.debug("Distance to data station %s: %.2f m" % (current_data_station.identity, distance))
                time.sleep(0.5)

            logging.info("Arrived at data station [%s]" % current_data_station.identity)

            logging.debug("Setting airspeed to AIRSPEED_SLOW: %.2f m/s" % self.AIRSPEED_SLOW)
            self.__vehicle.airspeed = self.AIRSPEED_SLOW

            # Block until drone is in loiter mode
            logging.debug("Engaging LOITER mode...")
            while str(self.__vehicle.mode.name) != "LOITER":
                self.__vehicle.mode = VehicleMode("LOITER")

            # Mark data station object as arrived
            current_data_station.drone_arrived = True

            # Create a download worker with reference to current_data_station
            download_worker = Download(current_data_station,
                                       self.DOWNLOAD_CONNECTION_TIMEOUT_SECONDS,
                                       self.DOWNLOAD_READ_WRITE_TIMEOUT_SECONDS)

            try:
                # This throws an error if the connection times out
                download_worker.connect()

                # Spawn download thread
                download_thread = threading.Thread(target=download_worker.start)
                download_thread.start()

                # Attempt to join the thread after timeout, if still alive the download timed out
                download_thread.join(self.OVERALL_DOWNLOAD_TIMEOUT_SECONDS)

                if download_thread.is_alive():
                    logging.info("Download timeout: Download cancelled")
                else:
                    logging.info("Download complete")

            except Exception as e:
                logging.error(e)

            # Attempt to turn off camera trap
            logging.info("Sending XBee POWER_OFF command...")
            # TODO: uncomment this when XBee is redone
            # self.__xbee.sendCommand('POWER_OFF', identity=current_data_station.identity, timeout=15)

            # FIXME: Why wait, why not continue only when we know trap is off? Is there a way to know?
            # time.sleep(15)  # wait 15 seconds to turn off camera trap

            logging.info("Continuing mission...")

            # Change back from LOITER to AUTO to continue previously uploaded mission
            logging.debug("Engaging AUTO mode...")
            while str(self.__vehicle.mode.name) != "AUTO":
                self.__vehicle.mode = VehicleMode("AUTO")
                self.__vehicle.airspeed = self.AIRSPEED_FAST
                time.sleep(1)

            logging.info("Airspeed set to %.2f m/s" % float(self.AIRSPEED_FAST))

            next_waypoint = self.__vehicle.commands.next

        # Return to home using fixed-wing landing sequence
        # (loiter to altitude and then begin final approach on tangent heading)
        logging.info("Beginning landing sequence...")

        # Monitor final approach to runway
        current_altitude = self.__vehicle.location.global_relative_frame.alt
        while current_altitude >= 0.5:
            current_altitude = self.__vehicle.location.global_relative_frame.alt
            logging.debug("Landing: Current altitude: %.2f m" % current_altitude)
            time.sleep(1)

        self.isNavigationComplete = True

        logging.info('Mission complete')
