# User guide

## Introduction
This guide will take you through how to use the QGIS GeoNode plugin to access GeoNode instances resources inside QGIS.
The following sections will elaborate on how to connect GeoNode instances, browse, filter and load the GeoNode resources.
Also the guide will highlight the differences between using the QGIS GeoNode plugin compared to the current QGIS GeoNode
integration which has been implemented in the QGIS core.

## Add a GeoNode instance
To add a GeoNode instance follow the below steps.

1. Open the main plugin provider widget by opening the data source manager dialog and click 
   "GeoNode Plugin Provider" item.
   
   ![GeoNode Plugin Provider](https://github.com/kartoza/qgis_geonode/raw/main/docs/images/user_guide/data_source_manager-qgis_geonode.png)
  
2. Inside "Connection" group box, click "New" button, a connection dialog will be shown.
3. Enter the GeoNode instance details "Name"  and "URL", if the instance supports authentication, you can
choose the authentication configurations for the instance using the QGIS authentication configuration selector widget available on the connection dialog.
4. Through the "API version" list choose the API that the connection should be connected to with. They
are two options at the moment, CSW API and the API version 2 the latter is available from GeoNode instances that use the
   master version. Click the "auto detect" button, to automatically detect and select the API version for the GeoNode instance.
5. There is button with a label "Test Connection" can be used to test if the GeoNode connection is valid. If the
connection is valid "Connection is valid" message will be displayed on the message bar otherwise a "Connection is invalid" error message will be shown.
6. Click "Ok" button after finishing adding all the details and the connection will be added.



### GeoNode API V2
To be written...


### GeoNode API CSW
To be written...


## Search and load GeoNode layer into QGIS

- Searching layers
  
  Make sure the intended GeoNode instance connection is selected from the connections list inside the Connection 
  group box, then click the "Search Geonode" button, a progress bar will be shown with a message "Searching...", 
  after searching is complete a list of search results will be populated in a scroll area below the search buttons.
  
  Example search results
  ![search results](https://github.com/kartoza/qgis_geonode/raw/main/docs/images/user_guide/example_search_results.png)
  
  - Using the search filters
    
    The plugin supports adding filters in the resource search, the current available search filters are on `title`, `abstract`, `keywords`, `categories`, `resources types`, 
    `temporal extent` and `publication date` properties. 
    
    Filtering using `title`, `abstract` and `keywords` will search for resources that 
    contains the corresponding values. 
    
    Using the `category` or the `resource types` will return resources
    that have the exact match on the values.
    
    While filtering using the `temporal extent` and/or `publication date` will return resources that have greater 
    than the start datetime and less than the end datetime in either of the properties, the start and end datetime are exclusive.
    
    The support for `spatial extent` is not yet implemented.

- Ordering results

  When searching for resources the results are ordered using their `name` by default, currently it is the only field
  that is allowed for ordering results. Users can change the order of the results by checking a "Reverse order" checkbox
  left of the "Sort by" combo box.
- Checking a layer's page on the GeoNode instance
  
  All search results item contain a "Open in Browser" button, which when clicked opens the layer GeoNode page
  using the default browser.
  
- Loading a layer onto QGIS

  In each of the search result items there are buttons to enable loading the result resource using the available 
  QGIS OGC providers (WMS for maps, WFS for vector and WCS for raster resources), in order to load the layer in QGIS
  user will click the available buttons for the respective providers.
  
  For the vector based resources WFS button be available, raster resources will contain the WCS button and WMS always be
  available for all resources that support it, if there is a problem with the resource URI the OGC buttons will not 
  be available as the resource will not be loadable.

- Inspecting layer metadata
  
  When loading the layer inside QGIS, the provider also load the available metadata from GeoNode into QGIS 
  layer metadata. Users can go to the layer properties and select the Metadata page to view the added metadata after loading
  the layer.


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