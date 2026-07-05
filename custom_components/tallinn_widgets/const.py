"""Constants for the Tallinn Widgets integration."""

DOMAIN = "tallinn_widgets"

CONF_CONFIG_PATH = "config_path"
CONF_ELRON_NAME = "elron_sensor_name"
CONF_TRANSIT_NAME = "transit_sensor_name"
CONF_ELRON_SCAN_INTERVAL = "elron_scan_interval"
CONF_TRANSIT_SCAN_INTERVAL = "transit_scan_interval"
CONF_STATION_BOARD_BUS_STATION = "station_board_bus_station"
CONF_STATION_BOARD_TRAM_STATION = "station_board_tram_station"
CONF_STATION_BOARD_TRAIN_STATION = "station_board_train_station"
CONF_STATION_BOARD_WINDOW_MINUTES = "station_board_window_minutes"
CONF_STATION_BOARD_LIMIT = "station_board_limit"

DEFAULT_CONFIG_PATH = "/config/tallinn_widgets/config.json"
DEFAULT_TRANSIT_NAME = "Tallinn Transit Board"
DEFAULT_ELRON_NAME = "Tallinn Elron Trips"
DEFAULT_BUS_NAME = "Tallinn Bus Departures"
DEFAULT_TRAM_NAME = "Tallinn Tram Departures"
DEFAULT_TRAIN_NAME = "Tallinn Train Departures"
DEFAULT_TRANSIT_SCAN_SECONDS = 45
DEFAULT_ELRON_SCAN_SECONDS = 60
DEFAULT_STATION_BOARD_BUS_STATION = "A. Laikmaa"
DEFAULT_STATION_BOARD_TRAM_STATION = "Kadriorg"
DEFAULT_STATION_BOARD_TRAIN_STATION = "Keila"
DEFAULT_STATION_BOARD_WINDOW_MINUTES = 60
DEFAULT_STATION_BOARD_LIMIT = 80
