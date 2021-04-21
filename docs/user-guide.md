# User guide

## Introduction
This guide will take you through how to use the QGIS GeoNode plugin to access GeoNode instances resources inside QGIS.
The following sections will elaborate on how to connect GeoNode instances, browse, filter and load the GeoNode resources.
Also the guide will highlight the differences between using the QGIS GeoNode plugin compared to the current QGIS GeoNode
integration which has been implemented in the QGIS core.

## Add a GeoNode instance
To add a GeoNode instance follow the below steps.

1. Open the main plugin provider widget by opening the data source manager dialog and clicking 
   "GeoNode Plugin Provider" item.
2. Inside "Connection" group box, click "New" button, a connection dialog will be shown.
3. Enter GeoNode instance details "Name"  and "URL", if the instance supports authentication, you can
choose the authentication configurations for the instance using the selector widget available on the connection dialog.
4. Through the "API version" list choose the API that the connection should be connected to with. They
are two options at the moment, CSW API and the API version 2 the latter is available from GeoNode instances that use the
   master version. 
5. There is button with a label "Test Connection" can be used to test if the GeoNode connection is valid. If the
connection is valid "Connection is valid" message will be displayed on the message bar else "Connection is invalid" message will be shown.
6. Click "Ok" button after finishing adding all the details and the connection will be added.



### GeoNode API V2
To be written...


### GeoNode API CSW
To be written...


## Search and load GeoNode layer into QGIS

- Using the search filters
  
  Current available search filters are on `title`, `abstract`, `keywords`, `categories`, `resources types`, 
  `temporal extent`, `publication date` and `spatial extent` properties. 
  
  Filtering using `title`, `abstract` and `keywords` will search for resources that 
  contains the corresponding values. 
  
  Using the `category` or `resource types` will search for resources
  that exactly match the values.
  When filtering using the `temporal extent` and/or `publication date` the returned resources have greater 
  than the start datetime and less than the end datetime in either of the properties, the start datetime is inclusive
  while the end datetime is not included.
  
  The support for `spatial extent` is not yet implemented.

- Ordering results
  When searching for resources the results are ordered using their `name` by default, currently it is the only field
  that is allowed for ordering results. Users can change the order of the results by checking a "Reverse order" checkbox
  left of the "Ordering" combo box.
- Checking a layer's page on the GeoNode instance
  
  All search results item contain a "Open in Browser" button, which when clicked opens the layer GeoNode page
  in the default browser.
  
- Loading a layer onto QGIS
  In each of the search result items there are buttons to enable loading the result resource using the available 
  QGIS OGC providers (WMS for maps, WFS for vector and WCS for raster resources), in order to load the layer in QGIS
  user will click the available buttons for the respective providers.
  
  For vector based resources WFS button be available, raster resources will contain the WCS button and WMS always be
  available for all resources, if there is a problem with the resource URI the OGC buttons will not be available as the
  resource will not be loadable.

- Inspecting layer metadata
  When loading the layer inside QGIS, the plugin provider also load the available metadata from GeoNode into QGIS 
  layer metadata. Users can go to the layer properties and click Metadata tab to view the added metadata after loading
  layer.


## Synchronize a loaded layer with GeoNode
Not implemented yet


### Modify layer data
Not implemented yet


### Modify layer symbology
Not implemented yet


### Modify layer metadata
Not implemented yet


## Modify layer access permissions
Not implemented yet


## Upload new layer to GeoNode
Not implemented yet


## Delete layer from GeoNode
Not implemented yet