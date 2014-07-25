#! /usr/bin/env python

class PairedRead:
    def __init__(self, exonsA, exonsB, xs=None):
        ''' exon is a list of (start,end) tuples marking each exonic region of this read.
            xs indicates the strand on which this gene lies, as described in the SAM file format.
        '''
        self.exonsA = exonsA
        self.exonsB = exonsB
        self.xs = xs