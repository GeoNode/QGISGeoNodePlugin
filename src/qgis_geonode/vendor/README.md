# Vendorized packages

This project vendorizes the 
[packaging](https://packaging.pypa.io/en/latest/index.html) package. It does 
so in order to use its ability to parse 
[PEP440](https://www.python.org/dev/peps/pep-0440/)-compliant versions, as is 
the case with the GeoNode version, which we eventually need to parse. 
**Vendorized version: packaging 21.3**

In order to keep the vendorized code as small as possible, we only 
keep the following:

- `packaging.__init__`
- `packaging.__about__`
- `packaging._structures`
- `packaging.version`
- `LICENSE`
- `LICENSE.APACHE`
- `LICENSE.BSD`

The rest of the code has been removed.

The `packaging` project is dual-licensed, using either BSD-2-Clause or 
Apache-2.0.

Thanks to the original `packaging` contributors.
