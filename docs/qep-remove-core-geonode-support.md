!!! Note
    This is a **draft QGIS Enhancement Proposal.**

    It is the result of <https://github.com/kartoza/qgis_geonode/issues/154>

    When ready it will be submitted
    to the QGIS community for appreciation and voting. For now, we are working on the
    text.

# QGIS Enhancement: Remove QGIS core GeoNode provider and replace it with a Python plugin

**Date** 2021/05/DD

**Authors** Ricardo Silva (@ricardogsilva), Samweli Mwakisambwe (@Samweli)

**Contact** ricardo at kartoza dot com

**maintainer** @ricardogsilva

**Version** QGIS 3.22


# Summary

This is a proposal for removing support for [GeoNode] from QGIS core and replace it 
with a Python plugin.

GeoNode is currently undergoing a comprehensive refactor of its web APIs.
change is likely to introduce disruption in the current QGIS integration. Moreover, GeoNode is also
adding a set of new features that will enable a richer user experience for third party integrations.

In order to keep up with the changes in GeoNode and to make it easier to ship them, we propose to remove
GeoNode support from QGIS core and introduce a GeoNode plugin instead.


## Current GeoNode support in QGIS

The current GeoNode support in QGIS consists in the existence of a core provider for discovering 
GeoNode layers and loading them into QGIS.


### Limitations of the current GeoNode support

- Release cycles of QGIS and GeoNode are not aligned.

- Maintenance burden is on core QGIS development team
  
- Relies on OGC webservices for presenting available layers to the user. 
  
  The OGC WMS/WFS/WCS webservices provide very limited support for searching and filtering 
  available datasets. The common strategy is to get all existing datasets and then provide 
  filtering capabilities on the client side. This becomes problematic when GeoNode 
  instances have a large number of datasets, as the time it takes to retrieve the list of 
  datasets becomes prohibitive.
  
- Searching existing layers offers little filtering capabilities. The current GeoNode support
  allows filtering layers based solely on their title.
  
- Loaded layers are disconnected from the remote GeoNode instance - no metadata, no link to GeoNode



## Proposed Solution

We will replace the current GeoNode support in QGIS core with a Python plugin. This plugin shall offer
improved support for newer GeoNode versions and will also provide reduced functionality in a 
backwards-compatible way.

The plugin shall remain independent from QGIS core. It will be available at the official QGIS plugins 
repository and interested users shall have to download it via the QGIS Plugin Manager.

It will be maintained by Kartoza and will have its own release cycle.

### Main objectives

- Provide a better user experience for finding relevant GeoNode layers.
- Allow loading GeoNode layer data, metadata and symbology into QGIS
- Provide support for uploading QGIS layers, metadata and symbology to remote 
  GeoNode instances
  

### Plugin description

#### Searching for new layers 
#### Inspecting layer metadata
#### Loading layers



### Example(s)

The plugin is currently being developed and is available for public review and testing. It can be found at:

https://kartoza.github.io/qgis_geonode/

For easier testing we have set up a custom QGIS plugin repository. Relevant installation instructions are 
available at the plugin website.


### Affected Files

The main changes to QGIS core brought by this QEP shall be removal of existing code.

List of all files that will be removed from QGIS core:


#### Header files that will be removed
TODO

#### Implementation files that will be removed
TODO

#### Tests that will be removed
TODO


## Performance Implications

QGIS core's performance shall be unaffected by the changes proposed in this QEP as no new features are 
being introduced

As for the workflows related to interacting with GeoNode from within QGIS:

- Searching for layers, there will be an increase in performance
  
- Loading layers onto QGIS shall show similar performance as the plugin is already using QGIS Tasks to
  perform all IO actions in background threads
  
- Saving QGIS layers on remote GeoNode instances will also make use of async tasks running on the 
  background
  


## Further Considerations/Improvements

*(optional)*

## Backwards Compatibility

The QGIS GeoNode plugin is being developed with backwards compatibility in mind. There is support for
a legacy API client, which provides read-only support for searching and loading GeoNode layers in QGIS.

## Issue Tracking ID(s)

*(optional)*

## Votes

(required)


[GeoNode]: https://geonode.org