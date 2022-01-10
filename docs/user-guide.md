# User guide


The plugin also adds a new _Geonode_ section to a QGIS layer's 
_Layer Properties_ dialogue. This section allows users to:

- [Upload QGIS layers to GeoNode]()
- [Reload/upload the style of a layer that came from GeoNode]()
- [Reload/upload some metadata attributes of a layer that came from GeoNode]()


## Managing GeoNode connections

The QGIS GeoNode plugin adds a new _Geonode Plugin_ section to the QGIS Data
Source Manager dialogue. This section can be used to add new GeoNode
connections, search for existing datasets and load them as QGIS layers. 


### Add a new GeoNode connection

![Add GeoNode connection](images/user_guide/manage_geonode_connection.png)

In order to add a new GeoNode connection:

1. Open the QGIS `Data Source Manager (Ctrl + L)` and go to the _GeoNode Plugin_ 
    section
  
2. Add a new GeoNode instance connection, by clicking the `New` button

3. A new dialogue is shown. This dialogue requests the following details of
   the GeoNode connection being created:

    | Parameter | Description |
    | --------- | ----------- |
    | Name | The name used by QGIS to refer to this connection |
    | GeoNode URL | The base URL of the GeoNode being connected to (_e.g._ <https://stable.demo.geonde.org>) |
    | Authentication | Whether to use authentication to connect to GeoNode or not. See the [Configuring authentication](#configuring-authentication) section below for more details on how to configure authenticated access to GeoNode |
    | Page size | How many search results per page shall be shown by QGIS. This defaults to `10` |

5. Optionally you may now click the `Test Connection` button. QGIS will then
    try to connect to GeoNode in order to discover what version of GeoNode is
    being used by the remote server.

    Upon a successful connection, the detected GeoNode version will be shown
    below. Depending on the detected GeoNode version, the plugin may not be
    able to offer all of its functionalities. The supported capabilities are
    listed in the `API client capabilities` section. Check the 
    [Supported capabilities](#supported-capabilities) section below for more
    information about capabilities

6. Finally, accept the new connection dialogue by clicking the `Ok` button. 
    Your new connection is now ready to be used.


### Edit an existing connection

In order to edit the details of an existing connection, just re-open the 
`QGIS Data Source Manager (Ctrl + L)`, go to the `GeoNode plugin` section, 
select the relevant connection from the `Connections` dropdown and click the
`Edit` button. A dialogue similar to the one discussed above in the 
[Add a new GeoNode connection](#add-a-new-geonode-connection) section shall be
shown with the connection details ready for editing


### Remove a GeoNode connection

In order to remove an existing connection, re-open the
`QGIS Data Source Manager (Ctrl + L)`, go to the `GeoNode plugin` section,
select the relevant connection from the `Connections` combo box and click the
`Remove` button. A confirmation dialogue will ask whether to really remove the
connection. Upon acceptance of this dialogue, the connection will be removed.


### Configure authentication

!!! note
    In order to be able to gain authenticated access to a GeoNode connection 
    you will need to request that one of the GeoNode administrators create an 
    **OAuth2** application and provide you with the following relevant details:

    - _Client ID_
    - _Client Secret_

![Authentication example](images/user_guide/authentication_example.png)

The plugin is able to authenticate to remote GeoNode instances by using
OAuth2 authentication. Most OAuth2 grant types implemented in QGIS are 
supported. We recommend using the `Authorization Code` grant type. In order 
to configure such an authentication:

1. Open the main QGIS authentication settings dialogue by going to 
    `Settings -> Options...` in the main QGIS menu bar and then access the 
    `Authentication` section

2. Press the `Add new authentication configuration button`. A new dialogue is
    shown. In this dialogue, fill in the following details:

    | Parameter | Description |
    | --------- | ----------- |
    | Name | The name used by QGIS to refer to the authentication configuration |
    | Authentication type | Select the `OAuth2 authentication` option from the dropdown |
    | Request URL | This is derived from the GeoNode base URL and takes the form `<geonode-base-url>/o/authorize/`, _e.g._ <https://stable.demo.geonode.org/o/authorize/> |
    | Token URL | This is derived from the GeoNode base URL and takes the form `<geonode-base-url>/o/token/`, _e.g._ <https://stable.demo.geonode.org/o/token/> |
    | Client ID | The client ID you got from your GeoNode administrator |
    | Client Secret | The client secret you got from your GeoNode administrator |
    
    The remaining fields can be left at their default values

4. Now when 
   [configuring a new GeoNode connection](#add-a-new-geonode-connection), 
   select this newly created authentication configuration in order to have the
   GeoNode connection use it
   

## Searching GeoNode datasets

![search results](images/user_guide/search_results.png)

After having configured a GeoNode connection, you may now use the plugin 
to search and load GeoNode datasets onto QGIS

1. Select the relevant connection from the dropdown list
2. Set any desired filters. Depending on the detected GeoNode version, the 
    following search filters may be available:

    | Search filter | Description |
    | ------------- | ----------- |
    | Title | The resource title is used to filter search results and returning records that contains the supplied title |
    | Abstract | Same as the title filter, records that contains the provided abstract value will be returned |
    | Keywords | Search will filter all resources that have keywords that exactly matches the selected keyword |
    | Topic Category | Filters the resources that their categories exactly matches the selected category |
    | Resources types | Filters resources based on the selected resource type |
    | Temporal extent | This filter used to select resources based on the stored temporal extent. Two fields `start` and `end` are used to represent the beginning and end of the extent respectively, during filtering both fields values are excluded. When both fields are supplied, resources containing temporal extent that is greater than `start` and less than `end` will be returned. If only `start` is provided, resources with the temporal extent beginning that is greater than `start` will be returned, if only `end` is provided resource with temporal extent end that is less than `end` will be returned |
    | Publication date | This filter has similar conditions as the Temporal extent filter, the difference here is the filter is applied to the resource's publication date and not the resources temporal extent |
    | Spatial Extent | The spatial extent filter is used to filter resources based on their geospatial extent, the extent can be filled by using a QGIS layer extent, map canvas extent or values can be manually added |

3. Choose which field to use for sorting the search results and whether 
   to reverse the sort order.

    !!! note
        Sorting is performed by the remote GeoNode server. Therefore it must be parametrized 
        before actually searching the remote. If you wish to change the sort order after having
        already performed a search then you need to press the `Search GeoNode` button again.

3. Press the `Search Geonode` button. The plugin proceeds to contact the 
   remote GeoNode instance and search for available datasets.

After searching is complete a list of search results is shown below the 
search buttons. If a large number of results has been found you may use the 
`previous` and `next` buttons to eventually inspect all of them.


### Search results

Each dataset shown on the search results list features the following elements:

| Parameter | Description |
| --------- | ----------- |
| Title | The title of the dataset |
| Dataset type | Wheter the dataset is a `vector` or a `raster` |
| Abstract | Brief description about the dataset |
| Thumbnail | Small image representation of the dataset |
| **Load layer via WMS** | Button to allow loading the dataset onto QGIS as a WMS layer |
| **Load via WFS/WCS** | Depending on the type of dataset, a button to load the dataset onto QGIS either as a WFS (for vectors) or WCS (for raster) layer |
| Open dataset in web browser | Button to open your web browser and visit the original dataset URL on the remote GeoNode instance |

  
### Inspecting layer metadata
  
When loading the layer inside QGIS, the layer metadata from GeoNode are added into the loaded layer as
QGIS layer metadata.

To view the added metadata, right-click on the added layer and click _Properties..._  then from the 
Properties dialog select the _Metadata_ page.

Image showing metadata page that contains metadata for layer with title 'ARANDANO BRIGITTA 2030' 
from the GeoNode demo server
![GeoNode demo OAuth2 configuration](images/user_guide/layer_metadata.png)


## Supported capabilities

Depending on the version of GeoNode detected, the plugin may allow performing
different actions. These are classified as a set of capabilities.

| Capability | Available on GeoNode version | Description                                                                     |
| ---------- | ---------------------------- |---------------------------------------------------------------------------------|
| FILTER_BY_TITLE | All | Allows searching for GeoNode datasets by a sub-string present on their title    |
| FILTER_BY_ABSTRACT | All | Allows searching for GeoNode datasets by a sub-string present on their abstract | 
| FILTER_BY_RESOURCE_TYPES | All | Allows filtering GeoNode datasets by their layer type (`vector` or `raster`)    |
| FILTER_BY_KEYWORD | >= 3.3.0 | Allows filtering GeoNode datasets by a keyword                                  |
| FILTER_BY_TOPIC_CATEGORY | >= 3.3.0 | Allows filtering GeoNode datasets by their ISO topic category                   |
| FILTER_BY_TEMPORAL_EXTENT |
| FILTER_BY_PUBLICATION_DATE |
| FILTER_BY_SPATIAL_EXTENT |
| LOAD_LAYER_METADATA |
| MODIFY_LAYER_METADATA |
| LOAD_VECTOR_LAYER_STYLE |
| LOAD_RASTER_LAYER_STYLE |
| MODIFY_VECTOR_LAYER_STYLE |
| MODIFY_RASTER_LAYER_STYLE |
| LOAD_VECTOR_DATASET_VIA_WMS |
| LOAD_VECTOR_DATASET_VIA_WFS |
| LOAD_RASTER_DATASET_VIA_WMS |
| LOAD_RASTER_DATASET_VIA_WCS |
| UPLOAD_VECTOR_LAYER |
| UPLOAD_RASTER_LAYER |


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
