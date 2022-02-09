# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]



## [0.9.5] - 2022-02-09

### Added
- Add new WFS version config option and default to WFS v1.1.0

### Fixed
- Remove unsupported f-string formatting on Python3.7
- Assign `UNKNOWN` as dataset type when the remote does not report it


## [0.9.4] - 2022-02-07

### Added
- Add support for HTTP Basic Auth when connecting to GeoNode deployments featuring version 3.3.0 or later


## [0.9.3] - 2022-01-20

### Fixed
- Improve compatibility with Python 3.7 when exporting SLD for raster layers
- Fix network access manager not using correct timeout for layer uploads


## [0.9.2] - 2022-01-18

### Fixed
- Do not use QgsNetworkAccessManager features introduced after QGIS 3.18


## [0.9.1] - 2022-01-14

### Fixed
- Fix layer properties dialogue not opening correctly for non-GeoNode layers
- Improve plugin metadata fields when displayed in QGIS plugin repo list
- Do not use typing.Final in order to support PYthon 3.7


## [0.9.0] - 2022-01-12

### Added
- Add connection capabilities and detected version details
- Connection test now uses auth credentials, if available

### Changed
- Layer uploads also send SLD style
- Update user guide

### Fixed
- Fix re-download of metadata for loaded layers
- Fix dataset abstract not being shown on the UI anymore


## [0.5.0] - 2021-12-29

### Added
- Allow uploading QGIS layers to GeoNode as new datasets

### Fixed
- QGIS plugins menu no longer shows empy reference to this plugin


## [0.4.0] - 2021-12-20

### Added
- Allow loading and saving layer title and abstract from/to GeoNode

### Changed
- Bump minimum QGIS version to 3.18


## [0.3.4] - 2021-12-17

### Added
- Modify style of GeoNode layer and save it on the remote GeoNode

### Changed
- Network fetcher task is now able to perform PUT requests
- Better handling of network errors


## [0.3.3] - 2021-11-22

### Fixed

- This release is functionally equivalent to v0.3.2


## [0.3.2] - 2021-11-22 - [YANKED]

### Changed
- Introduce compatibility with the latest developments of upstream GeoNode API


## [0.3.1] - 2021-05-07

### Added
- Persist current search filters between restarts of QGIS
- Add icon to button that fetches keywords
- Improve user feedback when testing connections

### Fixed
- Improved layer loading with the CSW API
- Fix incorrect pagination results with the CSW API


## [0.3.0] - 2021-04-07

### Added
- Allow filtering searches by temporal extent and publication date
- Add ordering of search results
- Add Changelog to the online documentation
- Further improve the look of search results

### Changed
- All HTTP requests are now done in a background thread to avoid blocking QGIS UI
- Load layers in a background thread in order to avoid blocking QGIS UI
- Improve feedback shown when searching and loading layers
- Move Title search filter out of the collapsible group, so that it is easier to access

### Fixed
- Improved error handling
- Fix incorrect visibility of the Search/Next/Previous search buttons
- Reset pagination when pressing Search button
- Remove unused Add/Close buttons on datasource manager dialogue


## [0.2.0] - 2021-02-28

### Added
- Add initial support for earlier GeoNode versions
- Initial support for search filters
- Add support for applying a vector layer's default SLD style when loading

### Changed
- Improve look of search results

### Fixed
- Fix invalid update date for versions released via custom plugin repo


## [0.1.1] - 2021-02-02

### Fixed
- Invalid tag format in previous version prevented automated distribution to our custom QGIS repo


## [0.1.0] - 2021-02-02 [YANKED]

### Added
- Load GeoNode layers into QGIS
- Load a GeoNode metadata into the corresponding QGIS layer
- Manage GeoNode connections through the plugin GUI
- Improve plugin metadata and documentation

### Fixed
- Current connection settings are now always up-to-date with the GUI


## [0.0.9] - 2021-01-11

### Fixed
-  Invalid plugin zip name


## [0.0.8] - 2021-01-08

### Fixed
-  Remove pycache files from plugin zip


## [0.0.7] - 2021-01-08

### Fixed
-  Invalid CI settings


## [0.0.6] - 2021-01-08

### Fixed
-  Invalid CI settings


## [0.0.5] - 2021-01-08

### Added
-  Initial project structure
-  Add infrastructure for automated testing
-  Add infrastructure for managing releases
-  Add geonode API client


[unreleased]: https://github.com/kartoza/qgis_geonode/compare/v0.9.5...main
[0.9.5]: https://github.com/kartoza/qgis_geonode/compare/v0.9.5...main
[0.9.4]: https://github.com/kartoza/qgis_geonode/compare/v0.9.4...main
[0.9.3]: https://github.com/kartoza/qgis_geonode/compare/v0.9.3...main
[0.9.2]: https://github.com/kartoza/qgis_geonode/compare/v0.9.2...main
[0.9.1]: https://github.com/kartoza/qgis_geonode/compare/v0.9.1...main
[0.9.0]: https://github.com/kartoza/qgis_geonode/compare/v0.9.0...main
[0.5.0]: https://github.com/kartoza/qgis_geonode/compare/v0.5.0...main
[0.4.0]: https://github.com/kartoza/qgis_geonode/compare/v0.4.0...main
[0.3.4]: https://github.com/kartoza/qgis_geonode/compare/v0.3.4...main
[0.3.3]: https://github.com/kartoza/qgis_geonode/compare/v0.3.3...main
[0.3.2]: https://github.com/kartoza/qgis_geonode/compare/v0.3.2...main
[0.3.1]: https://github.com/kartoza/qgis_geonode/compare/v0.3.1...main
[0.3.0]: https://github.com/kartoza/qgis_geonode/compare/v0.3.0...main
[0.2.0]: https://github.com/kartoza/qgis_geonode/compare/v0.2.0...main
[0.1.1]: https://github.com/kartoza/qgis_geonode/compare/v0.1.1...main
[0.1.0]: https://github.com/kartoza/qgis_geonode/compare/v0.1.0...main
[0.0.9]: https://github.com/kartoza/qgis_geonode/compare/v0.0.9...main
[0.0.8]: https://github.com/kartoza/qgis_geonode/compare/v0.0.8...main
[0.0.7]: https://github.com/kartoza/qgis_geonode/compare/v0.0.7...main
[0.0.6]: https://github.com/kartoza/qgis_geonode/compare/v0.0.6...main
[0.0.5]: https://github.com/kartoza/qgis_geonode/compare/v0.0.5...main
