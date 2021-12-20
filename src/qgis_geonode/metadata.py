import qgis.core

from .apiclient import models
from .utils import tr


def populate_metadata(
    metadata: qgis.core.QgsLayerMetadata, dataset: models.Dataset
) -> qgis.core.QgsLayerMetadata:
    metadata.setIdentifier(str(dataset.uuid))
    metadata.setTitle(dataset.title)
    metadata.setAbstract(dataset.abstract)
    metadata.setLanguage(dataset.language)
    metadata.setKeywords({"layer": dataset.keywords})
    if dataset.category:
        metadata.setCategories([dataset.category])
    if dataset.license:
        metadata.setLicenses([dataset.license])
    if dataset.constraints:
        constraints = [qgis.core.QgsLayerMetadata.Constraint(dataset.constraints)]
        metadata.setConstraints(constraints)
    metadata.setCrs(dataset.srid)
    spatial_extent = qgis.core.QgsLayerMetadata.SpatialExtent()
    spatial_extent.extentCrs = dataset.srid
    if dataset.spatial_extent:
        spatial_extent.bounds = dataset.spatial_extent.toBox3d(0, 0)
        if dataset.temporal_extent:
            metadata.extent().setTemporalExtents(
                [
                    qgis.core.QgsDateTimeRange(
                        dataset.temporal_extent[0],
                        dataset.temporal_extent[1],
                    )
                ]
            )
    metadata.extent().setSpatialExtents([spatial_extent])
    if dataset.owner:
        owner_contact = qgis.core.QgsAbstractMetadataBase.Contact(dataset.owner)
        owner_contact.role = tr("owner")
        metadata.addContact(owner_contact)
    if dataset.metadata_author:
        metadata_author = qgis.core.QgsAbstractMetadataBase.Contact(
            dataset.metadata_author
        )
        metadata_author.role = tr("metadata_author")
        metadata.addContact(metadata_author)
    links = []
    if dataset.thumbnail_url:
        link = qgis.core.QgsAbstractMetadataBase.Link(
            tr("Thumbnail"), tr("Thumbail_link"), dataset.thumbnail_url
        )
        links.append(link)
    if dataset.link:
        link = qgis.core.QgsAbstractMetadataBase.Link(
            tr("API"), tr("API_URL"), dataset.link
        )
        links.append(link)
    if dataset.detail_url:
        link = qgis.core.QgsAbstractMetadataBase.Link(
            tr("Detail"), tr("Detail_URL"), dataset.detail_url
        )
        links.append(link)
    metadata.setLinks(links)
    return metadata
