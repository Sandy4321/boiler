What is Boiler?
===============

Boiler is a SAM compression tool designed for downstream isoform assembly and quantitation. Boiler achieves a significant space improvement over other compression tools by discarding unnecessary fields such as sequence information and quality scores. It also tends to shuffle read pairings within highly-covered exons. However, Boiler will always return exact coverage levels over any region of the genome.

Boiler offers several fast queries for its compressed files. Users can query bundles, coverage or reads over any genome interval. Boiler also offers a 'counts' query that returns the read counts over all exons and junctions in a gtf file.

Installing Boiler
=================

You can download the latest version of Boiler from https://github.com/jpritt/boiler. Boiler requires Python 3 or higher to run. There are no other dependencies. You can also run Boiler with PyPy for faster execution.

Guide
^^^^^

.. toctree::
   :maxdepth: 2
   
   tutorial
   reference
