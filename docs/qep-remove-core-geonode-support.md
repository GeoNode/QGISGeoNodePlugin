!!! Note
    This is a **draft QGIS Enhancement Proposal.**

    It is the result of <https://github.com/kartoza/qgis_geonode/issues/154>

    When ready it will be submitted to the QGIS community for appreciation and 
    voting. For now, we are working on the text.

    When this QEP is submitted we will update this page to have a reference to it

# QGIS Enhancement: Remove QGIS core GeoNode provider and replace it with a Python plugin

**Date** 2021/06/DD

**Authors** Ricardo Silva (@ricardogsilva), Samweli Mwakisambwe (@Samweli)

**Contact** info at kartoza dot com

**maintainers** @ricardogsilva, @samweli

**Version** QGIS 3.22


# Summary

This is a proposal for removing support for [GeoNode] from QGIS core and replace it 
with a Python plugin.

QGIS currently has support for loading layers from GeoNode instances. This support is 
limited to public layers. Additionally, the current implementation only allows for simple
filtering of existing layers.

Additionally, GeoNode is currently undergoing a comprehensive refactor of its web APIs.
This change is likely to introduce disruption in the current QGIS integration. GeoNode is also
adding a set of new features that will enable a richer user experience for third party integrations.

In order to keep up with the changes in GeoNode and to make it easier to ship them, we propose to remove
GeoNode support from QGIS core and introduce a GeoNode Python plugin instead. The plugin shall improve upon
the current user experience and also add new features provided by the new GeoNode API. It
will be maintained by Kartoza as an independent project from QGIS.


## Current GeoNode support in QGIS

The current GeoNode support in QGIS consists in the existence of a core provider for discovering 
GeoNode layers and loading them into QGIS. This provider implements a wrapper on top of the WMS, WFS, WCS 
providers, which are what is actually used to load the layers onto QGIS.

This functionality is accessible both via the QGIS Datasource Manager and via the QGIS browser.

Briefly, main user workflows are:

- Configure and manage existing GeoNode connections
  
- Connect to a GeoNode instance and get a list of all existing layers, segregated by the respective OGC 
  service that exposes the layer
  
- Load a GeoNode layer onto QGIS

- 


### Limitations of the current GeoNode support

- **Discovering layers is not very user-friendly** - Upon connecting to the remote GeoNode instance, 
  QGIS proceeds discover existing layers by using OGC webservices. The OGC WMS/WFS/WCS webservices 
  provide very limited support for searching and filtering available datasets. The common strategy 
  is to get all existing resources and then provide filtering capabilities on the client side. This 
  becomes problematic when GeoNode instances have a large number of datasets, as the time it takes 
  to retrieve the list of all WMS layers, then retrieving a list of all WFS layers, then retrieving
  a list of all WCS layers becomes prohibitive. This becomes apparent just by trying out the GeoNode
  integration in QGIS using the GeoNode demo server:
  
  <https://master.demo.geonode.org>
  
  As an example, at the time of writing this QEP, connecting to the GeoNode demo instance from inside QGIS
  takes about 15 seconds just to get a listing of existing resources.

  There is also no way to filter layers based on other properties other than their title. However, 
  GeoNode does expose additional metadata about each layer that can be used to perform more efficient
  searching and discovery of layers, such as:
  
  - spatial extent
  - temporal extent
  - ISO topic category
  - ad-hoc keywords
  - layer thumbnails
  - etc.
  
  The current QGIS GeoNode integration does not use these additional properties.

- **Layer metadata is not exposed in QGIS** -

- **There is no support for user authentication** - GeoNode is able to serve both public and private 
  resources. The private resources are protected with authentication using OAuth2. However, even 
  though QGIS has built-in support for authenticating to remote servers using OAuth2, the GeoNode 
  integration does not use it.
  
  This means that, in order to be able to load private GeoNode layers, endusers must bypass the GeoNode
  integration and directly configure a connection to the underlying OGC server used by GeoNode (which 
  is GeoServer)

- **Layer loading is synchronous** - Loading GeoNode layers is still using a synchronous method, which
  does not seem inline with newer QGIS capabilities of performing heavy work in background threads and
  have a responsive UI at all times.

- **Release cycles of QGIS and GeoNode are not aligned** - Since GeoNode's API support is evolving
  it can happen that some of the existing QGIS integration features stops working due to a change in 
  GeoNode.

- **Maintenance burden is on core QGIS development team** - Integration with GeoNode, while being a
  meritable feature, does not seem to be part of QGIS core focus. Additionally, there does not seem to
  be much demand for nor interest in maintaining this integration (lack of a hero maintainer). As a 
  result, maintaining the GeoNode integration becomes a burden on the team of core QGIS developers.
  This leads to a degradation of the User Experience and also to a sense of abandonment of this set 
  of features.
  

## Proposed Solution

Kartoza proposes to replace the current GeoNode support in QGIS core with a Python plugin. This plugin 
shall address the limitations mentioned above and also implement support for new GeoNode features. 

The plugin shall be maintained by Kartoza and it will have its own release cycle, independent from QGIS core. 
We will aim for it to become an exemplar citizen of the wider QGIS plugin ecosystem. Naturally, it shall 
be available on the official QGIS plugins repository and interested users shall have to download it via 
the QGIS Plugin Manager.

### Main objectives

The upcoming plugin aims to become a first-class client of GeoNode API and provide workflows for both reading and 
writing data back to GeoNode. Main goals are:

1. Provide a better user experience for discovering relevant GeoNode layers;
  
1. Allow loading GeoNode layer **data**, **metadata** and **symbology** into QGIS;

1. Allow authenticated access to GeoNode;
  
1. Provide support for uploading QGIS layers, metadata and symbology to remote 
  GeoNode instances;
  

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