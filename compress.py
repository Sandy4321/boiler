#! /usr/bin/env python3
import alignments
import re
import read
import pairedread
import junction
import bisect
import zlib
import binaryIO
import math

class Compressor:
    aligned = None

    sectionLen = 100000

    def compress(self, samFilename, compressedFilename, binary=False):
        ''' Compresses the alignments to 2 files, one for unspliced and one for spliced

            file_prefix: Prefix for all output file names
        '''

        # Read header
        header = ''
        with open(samFilename, 'r') as f:
            for line in f:
                if line[0] == '@':
                    header += line
                else:
                    break
        self.chromosomes = self.parseSAMHeader(header)
        self.aligned = alignments.Alignments(self.chromosomes)

        with open(samFilename, 'r') as f:
            self.parseAlignments(f)
        
        if binary:
            # Write spliced and unspliced information
            with open(compressedFilename, 'wb') as f:                
                binaryIO.writeChroms(f, self.aligned.chromosomes)
                exonBytes = binaryIO.writeExons(f, self.aligned.exons)

                self.compressSpliced(f, binary, exonBytes)
                self.compressUnspliced(f, binary)

            # Write exons and index information
            compressed = None
            with open(compressedFilename, 'rb') as f:
                compressed = f.read()
            with open(compressedFilename, 'wb') as f:
                f.write(bytes('#' + '\t' + '\t'.join([str(i) for i in self.splicedIndex]) + '\n', 'UTF-8'))
                for k,v in self.unsplicedIndex.items():
                    f.write(bytes('#' + str(k) + '\t' + '\t'.join([str(i) for i in v]) + '\n', 'UTF-8'))
                for k,v in self.unsplicedExonsIndex.items():
                    f.write(bytes('#' + str(k) + '\t' + '\t'.join([str(i) for i in v]) + '\n', 'UTF-8'))

                f.write(compressed)
        else:
            # Write spliced and unspliced information
            with open(compressedFilename, 'w') as f:
                if len(self.aligned.spliced) > 0:
                    self.compressSpliced(f, binary)

                f.write('/\n')

                if len(self.aligned.unspliced) > 0:
                    self.compressUnspliced(f, binary)

            # Write exons and index information
            compressed = None
            with open(compressedFilename, 'r') as f:
                compressed = f.read()
            with open(compressedFilename, 'w') as f:
                chroms = []
                for k,v in self.aligned.chromosomes.items():
                    chroms.append(str(k)+','+str(v))
                f.write('\t'.join(chroms) + '\n')

                f.write('\t'.join([str(e) for e in self.aligned.exons]) + '\n')

                f.write('#' + '\t' + '\t'.join([str(i) for i in self.splicedIndex]) + '\n')

                for k,v in self.unsplicedIndex.items():
                    f.write('#' + str(k) + '\t' + '\t'.join([str(i) for i in v]) + '\n')

                f.write(compressed)

    def compressSpliced(self, filehandle, binary=False, exonBytes=0):
        ''' Compress the spliced alignments to a single file

            filehandle: File to write to
        '''

        # Compute coverage levels across every exon junction
        junctions = dict()

        # For each exon, offset in file of first junction containing that exon
        self.splicedIndex = [-1] * len(self.aligned.exons)

        # Keep track of maximum read and fragment lengths
        maxReadLen = 0
        maxFragLen = 0

        for r in self.aligned.spliced:
            exonIds = r.exonIds

            if not r.xs == None:
                # XS is defined for this read
                key = '\t'.join([str(e) for e in exonIds]) + '\t' + r.xs + '\t' + str(r.NH)
                if not key in junctions:
                    covLength = 0
                    for e in exonIds:
                        covLength += self.aligned.exons[e+1] - self.aligned.exons[e]
                    junctions[key] = junction.Junction(exonIds, covLength)
                    junctions[key].xs = r.xs
                    junctions[key].NH = r.NH
                j = junctions[key]
            else:
                # XS not defined for this read, so see which one (+/-) is in the dict already or add + by default
                key1 = '\t'.join([str(e) for e in exonIds]) + '\t+\t' + str(r.NH)
                key2 = '\t'.join([str(e) for e in exonIds]) + '\t-\t' + str(r.NH)
                if key1 in junctions:
                    read.xs = '+'
                    j = junctions[key1]

                    key = key1
                elif key2 in junctions:
                    read.xs = '-'
                    j = junctions[key2]

                    key = key2
                else:
                    read.xs = '+'
                    covLength = 0
                    for e in exonIds:
                        covLength += self.aligned.exons[e+1] - self.aligned.exons[e]
                    junctions[key1] = junction.Junction(exonIds, covLength)
                    junctions[key1].xs = '+'
                    junctions[key1].NH = r.NH
                    j = junctions[key1]

                    key = key1

            
            # update junction coverage vector in dictionary
            if (r.lenLeft == 0 and r.lenRight == 0):
                for i in range(r.startOffset, len(j.coverage)-r.endOffset):
                    j.coverage[i] += 1
            else:
                for i in range(r.startOffset, r.startOffset+r.lenLeft):
                    j.coverage[i] += 1
                for i in range(len(j.coverage)-r.endOffset-r.lenRight, len(j.coverage)-r.endOffset):
                    j.coverage[i] += 1

            # update readLens
            if r.readLen in j.readLens:
                j.readLens[r.readLen] += 1
            else:
                j.readLens[r.readLen] = 1

                if r.readLen > maxFragLen:
                    maxFragLen = r.readLen

            # update left and right read lengths
            if r.lenLeft > 0 or r.lenRight > 0:
                if r.lenLeft in j.lensLeft:
                    j.lensLeft[r.lenLeft] += 1
                else:
                    j.lensLeft[r.lenLeft] = 1

                    if r.lenLeft > maxReadLen:
                        maxReadLen = r.lenLeft

                if r.lenRight in j.lensRight:
                    j.lensRight[r.lenRight] += 1
                else:
                    j.lensRight[r.lenRight] = 1

                    if r.lenRight > maxReadLen:
                        maxReadLen = r.lenRight

        # Determine the number of bytes for fragment and read lengths
        #fragLenBytes = binaryIO.findNumBytes(maxFragLen)
        readLenBytes = binaryIO.findNumBytes(maxReadLen)

        #binaryIO.writeVal(filehandle, 1, fragLenBytes)
        binaryIO.writeVal(filehandle, 1, readLenBytes)

        # Write number of junctions
        binaryIO.writeVal(filehandle, 2*exonBytes, len(junctions))

        # Write junction information
        sortedJuncs = sorted(junctions.keys(), key=lambda x: [int(n) for n in x.split('\t')[:-2]])
        i = 0
        for key in sortedJuncs:

            # get offset in file
            offset = filehandle.tell()
            exons = [int(e) for e in key.split('\t')[:-2]]
            for e in exons:
                if self.splicedIndex[e] == -1:
                    self.splicedIndex[e] = offset

            junc = junctions[key]

            if binary:
                binaryIO.writeJunction(filehandle, exonBytes, readLenBytes, junc)
            else:
                # write junction information
                filehandle.write('>' + key + '\n')

                # write read lengths
                filehandle.write('\t'.join( [str(k)+','+str(v) for k,v in junc.readLens.items()] ) + '\n')

                # Write left and right read lengths
                filehandle.write('\t'.join([str(k)+','+str(v) for k,v in junc.lensLeft.items()]) + '\n')
                filehandle.write('\t'.join([str(k)+','+str(v) for k,v in junc.lensRight.items()]) + '\n')

                # write coverage
                self.writeRLE(junc.coverage, filehandle)

    def compressUnspliced(self, filehandle, binary=False):
        ''' Compress the unspliced alignments as a run-length-encoded coverage vector

            filename: Name of file to compress to
        '''

        maxFragLen = 0
        maxReadLen = 0

        # sort reads into exons
        readExons = dict()
        coverages = dict()
        for i in range(len(self.aligned.unspliced)):
            r = self.aligned.unspliced[len(self.aligned.unspliced) - i - 1]

            if binary:
                # find maximum fragment and read lengths
                if r.lenLeft > maxReadLen:
                    maxReadLen = r.lenLeft
                if r.lenRight > maxReadLen:
                    maxReadLen = r.lenRight
                fragLen = r.exons[0][1] - r.exons[0][0]
                if fragLen > maxFragLen:
                    maxFragLen = fragLen

            if not r.NH in readExons:
                readExons[r.NH] = []
                for n in range(len(self.aligned.exons)-1):
                    readExons[r.NH] += [[]]

                if r.NH == 1:
                    coverages[r.NH] = [0] * self.aligned.exons[-1]
                else:
                    coverages[r.NH] = [ [0, self.aligned.exons[-1]] ]

            j = bisect.bisect_right(self.aligned.exons, r.exons[0][0])-1
            readExons[r.NH][j] += [len(self.aligned.unspliced) - i - 1]

            # update coverage vector
            if r.NH == 1:
                if r.lenLeft == 0 and r.lenRight == 0:
                    for base in range(r.exons[0][0], r.exons[0][1]):
                        coverages[r.NH][base] += 1
                else:
                    for base in range(r.exons[0][0], r.exons[0][0]+r.lenLeft):
                        coverages[r.NH][base] += 1
                    for base in range(r.exons[0][1]-r.lenRight, r.exons[0][1]):
                        coverages[r.NH][base] += 1
            else:
                if (r.lenLeft == 0 and r.lenRight == 0):# or (r.exons[0][0]+r.lenLeft > r.exons[0][1]-r.lenRight):
                    coverages[r.NH] = self.updateRLE(coverages[r.NH], r.exons[0][0], r.exons[0][1]-r.exons[0][0], 1)
                else:
                    coverages[r.NH] = self.updateRLE(coverages[r.NH], r.exons[0][0], r.lenLeft, 1)
                    coverages[r.NH] = self.updateRLE(coverages[r.NH], r.exons[0][1]-r.lenRight, r.lenRight, 1)

        if binary:
            # find length in bytes to fit fragment and read lengths
            fragLenBytes = binaryIO.findNumBytes(maxFragLen)
            readLenBytes = binaryIO.findNumBytes(maxReadLen)

            # Write number of exons and NH values
            binaryIO.writeVal(filehandle, 2, len(coverages))
            binaryIO.writeVal(filehandle, 4, self.sectionLen)
            binaryIO.writeVal(filehandle, 1, fragLenBytes)
            binaryIO.writeVal(filehandle, 1, readLenBytes)
            self.writeUnsplicedBinary(filehandle, readExons, coverages, fragLenBytes, readLenBytes)
        else:
            self.writeUnspliced(filehandle, readExons, coverages)

    def writeUnspliced(self, filehandle, readExons, coverages):
        breakpoints = range(0, self.aligned.exons[-1], self.sectionLen)

        # For each NH value and for each exon, store the byte offset in the file for the given exon in the coverage vector
        self.unsplicedIndex = dict()

        for NH in sorted(readExons.keys()):
            cov = coverages[NH]
            reads = readExons[NH]

            filehandle.write('#' + str(NH) + '\n')

            # Write coverage vector
            if NH == 1:
                offsets = [0] * len(breakpoints)
                for i in range(len(breakpoints)-1):
                    offsets[i] = filehandle.tell()
                    self.writeRLE(cov[breakpoints[i]:breakpoints[i+1]], filehandle)
                offsets[-1] = filehandle.tell()
                self.writeRLE(cov[breakpoints[-1]:], filehandle)

                self.unsplicedIndex[NH] = offsets
            else:
                offsets = [0] * len(breakpoints)

                pos = 0
                currBreakpoint = 0
                segmentRLE = []
                for c in cov:
                    if breakpoints[currBreakpoint] == pos:
                        offsets[currBreakpoint] = filehandle.tell()
                        currBreakpoint += 1

                    segmentEnd = pos+c[1]
                    while currBreakpoint < len(breakpoints) and breakpoints[currBreakpoint] < segmentEnd:
                        length = breakpoints[currBreakpoint] - pos
                        if length == 1:
                            filehandle.write(str(c[0]) + '\n')
                        else:
                            filehandle.write(str(c[0]) + '\t' + str(length) + '\n')

                        c[1] -= length
                        pos += length
                        offsets[currBreakpoint] = filehandle.tell()
                        currBreakpoint += 1

                    if c[1] == 1:
                        filehandle.write(str(c[0]) + '\n')
                    else:
                        filehandle.write(str(c[0]) + '\t' + str(c[1]) + '\n')
                    pos += c[1]

                self.unsplicedIndex[NH] = offsets

            # Write lengths for each exon
            for i in range(len(reads)):
                if len(reads[i]) > 0:
                    length = self.aligned.exons[i+1] - self.aligned.exons[i]

                    exonStart = self.aligned.exons[i]

                    # Distribution of all read lengths
                    readLens = dict()

                    # Distribution of all gap lengths in paired-end reads
                    lensLeft = dict()
                    lensRight = dict()

                    for readId in reads[i]:
                        read = self.aligned.unspliced[readId]

                        alignment = read.exons

                        start = alignment[0][0] - exonStart
                        end = alignment[0][1] - exonStart

                        # update read lengths distribution
                        length = end - start
                        if length in readLens:
                            readLens[length] += 1
                        else:
                            readLens[length] = 1

                        # update left and right read lengths
                        if read.lenLeft > 0 or read.lenRight > 0:
                            if read.lenLeft in lensLeft:
                                lensLeft[read.lenLeft] += 1
                            else:
                                lensLeft[read.lenLeft] = 1

                            if read.lenRight in lensRight:
                                lensRight[read.lenRight] += 1
                            else:
                                lensRight[read.lenRight] = 1

                    # Write bounds
                    filehandle.write('>' + str(i) + '\n')

                    # Write read lengths
                    filehandle.write('\t'.join([str(k)+','+str(v) for k,v in readLens.items()]) + '\n')

                    # Write left and right read lengths
                    filehandle.write('\t'.join([str(k)+','+str(v) for k,v in lensLeft.items()]) + '\n')
                    filehandle.write('\t'.join([str(k)+','+str(v) for k,v in lensRight.items()]) + '\n')

    def writeUnsplicedBinary(self, filehandle, readExons, coverages, fragLenBytes, readLenBytes):
        ''' Compress the unspliced alignments as a run-length-encoded coverage vector

            filename: Name of file to compress to
        '''

        # For each NH value and for each exon, store the byte offset in the file for the given exon in the coverage vector
        self.unsplicedIndex = dict()
        self.unsplicedExonsIndex = dict()

        breakpoints = range(0, self.aligned.exons[-1], self.sectionLen)

        for NH in sorted(readExons.keys()):
            binaryIO.writeVal(filehandle, 2, NH)

            cov = coverages[NH]
            reads = readExons[NH]

            # Write coverage vector
            if NH == 1:
                offsets = [0] * len(breakpoints)
                for i in range(len(breakpoints)-1):
                    offsets[i] = filehandle.tell()
                    binaryIO.writeCov(filehandle, binaryIO.RLE(cov[breakpoints[i]:breakpoints[i+1]]))
                offsets[-1] = filehandle.tell()
                binaryIO.writeCov(filehandle, binaryIO.RLE(cov[breakpoints[-1]:]))

                self.unsplicedIndex[NH] = offsets
            else:
                offsets = [0] * len(breakpoints)

                pos = 0
                currBreakpoint = 0
                segmentRLE = []
                for c in cov:
                    if breakpoints[currBreakpoint] == pos:
                        if len(segmentRLE) > 0:
                            binaryIO.writeCov(filehandle, segmentRLE)
                            segmentRLE = []
                        offsets[currBreakpoint] = filehandle.tell()
                        currBreakpoint += 1

                    segmentEnd = pos+c[1]
                    while currBreakpoint < len(breakpoints) and breakpoints[currBreakpoint] < segmentEnd:
                        length = breakpoints[currBreakpoint] - pos
                        segmentRLE.append([c[0], length])
                        
                        binaryIO.writeCov(filehandle, segmentRLE)
                        segmentRLE = []

                        c[1] -= length
                        pos += length
                        offsets[currBreakpoint] = filehandle.tell()
                        currBreakpoint += 1

                    segmentRLE.append(c)

                    pos += c[1]
                if len(segmentRLE) > 0:
                    binaryIO.writeCov(filehandle, segmentRLE)

                self.unsplicedIndex[NH] = offsets

            # Write lengths for each exon
            exonsIndex = [0] * len(reads)
            exonsIndex[0] = filehandle.tell()
            for i in range(len(reads)):
                if i > 0:
                    exonsIndex[i] = filehandle.tell() - exonsIndex[i-1]

                length = self.aligned.exons[i+1] - self.aligned.exons[i]

                exonStart = self.aligned.exons[i]

                # Distribution of all read lengths
                readLens = dict()

                # Distribution of all gap lengths in paired-end reads
                lensLeft = dict()
                lensRight = dict()

                for readId in reads[i]:
                    read = self.aligned.unspliced[readId]

                    alignment = read.exons

                    start = alignment[0][0] - exonStart
                    end = alignment[0][1] - exonStart

                    # update read lengths distribution
                    length = end - start
                    if length in readLens:
                        readLens[length] += 1
                    else:
                        readLens[length] = 1

                    # update left and right read lengths
                    if read.lenLeft > 0 or read.lenRight > 0:
                        if read.lenLeft in lensLeft:
                            lensLeft[read.lenLeft] += 1
                        else:
                            lensLeft[read.lenLeft] = 1

                        if read.lenRight in lensRight:
                            lensRight[read.lenRight] += 1
                        else:
                            lensRight[read.lenRight] = 1

                self.unsplicedExonsIndex[NH] = exonsIndex

                binaryIO.writeLens(filehandle, fragLenBytes, readLens)
                if len(readLens) > 0:
                    binaryIO.writeLens(filehandle, readLenBytes, lensLeft)
                    if len(lensLeft) > 0:
                        binaryIO.writeLens(filehandle, readLenBytes, lensRight)


    def parseAlignments(self, filehandle):
        ''' Parse a file in SAM format
            Add the exonic region indices for each read to the correct ChromosomeAlignments object
            
            filehandle: SAM filehandle containing aligned reads
        '''

        # paired reads that have not yet found their partner
        unpaired = dict()

        for line in filehandle:
            row = line.strip().split('\t')
            if len(row) < 5:
                continue

            chromosome = str(row[2])
            

            if not row[2] in self.chromosomes.keys():
                print('Chromosome ' + str(row[2]) + ' not found!')
                continue

            exons = self.parseCigar(row[5], int(row[3]))

            # find XS value:
            xs = None
            NH = 1
            for r in row[11 : len(row)]:
                if r[0:5] == 'XS:A:' or r[0:5] == 'XS:a:':
                    xs = r[5]
                elif r[0:3] == 'NH:':
                    NH = int(r[5:])

            
            if not row[6] == '*':
                if row[6] == '=':
                    pair_chrom = chromosome
                else:
                    pair_chrom = row[6]
                pair_index = int(row[7])

                self.aligned.processRead(read.Read(chromosome, exons, xs, NH), pair_chrom, pair_index)
            else:
                self.aligned.processRead(read.Read(chromosome, exons, xs, NH))

            '''
            if row[6] == '=':
                pair_index = int(row[7])
                self.aligned.processRead(read.Read(chromosome, exons, xs, NH), chromosome, pair_index)
            else:
                self.aligned.processRead(read.Read(chromosome, exons, xs, NH))
            '''

        self.aligned.finalizeExons()
        self.aligned.finalizeReads()

    def parseCigar(self, cigar, offset):
        ''' Parse the cigar string starting at the given index of the genome
            Returns a list of offsets for each exonic region of the read [(start1, end1), (start2, end2), ...]
        '''

        exons = []
        newExon = True

        # Parse cigar string
        match = re.search("\D", cigar)
        while match:
            index = match.start()
            length = int(''.join(cigar[:index]))

            if cigar[index] == 'N':
                # Separates contiguous exons, so set boolean to start a new one
                newExon = True
            elif cigar[index] == 'M':
                # If in the middle of a contiguous exon, append the length to it, otherwise start a new exon
                if newExon:
                    exons.append([offset, offset+length])
                    newExon = False
                else:
                    exons[-1][1] += length
            elif cigar[index] == 'D':
                # If in the middle of a contiguous exon, append the deleted length to it
                if not newExon:
                    exons[-1][1] += length

            offset += length
            cigar = cigar[index+1:]
            match = re.search("\D", cigar)

        return exons

    def parseSAMHeader(self, header):
        chromosomes = dict()
        for line in header.split('\n'):
            if line[0:3] == '@SQ':
                row = line.strip().split('\t')
                chromosomes[row[1][3:]] = int(row[2][3:])
        return chromosomes


    def RLE(self, vector):
        rle = []

        val = vector[0]
        length = 0
        for v in vector:
            if v == val:
                length += 1
            else:
                if length == 1:
                    rle.append([val])
                else:
                    rle.append([val, length])
                val = v
                length = 1

        if length == 1:
            rle.append([val])
        else:
            rle.append([val, length])

        return rle

    def updateRLE(self, RLE, start, length, value):
        i = 0

        while start > 0 and start >= RLE[i][1]:
            start -= RLE[i][1]
            i += 1

        if start > 0:
            RLE = RLE[:i] + [ [RLE[i][0], start], [RLE[i][0], RLE[i][1]-start] ] + RLE[i+1:]
            i += 1

        while length > 0 and length >= RLE[i][1]:
            RLE[i][0] += value
            if RLE[i][0] < 0:
                RLE[i][0] = 0

            length -= RLE[i][1]
            #if i > 0 and RLE[i][0] == RLE[i-1][0]:
            #    RLE = RLE[:i-1] + [ [RLE[i][0], RLE[i-1][1]+RLE[i][1]] ] + RLE[i+1:]
            #else:
            i += 1

        if length > 0:
            RLE = RLE[:i] + [ [max(RLE[i][0]+value,0), length], [RLE[i][0], RLE[i][1]-length] ] + RLE[i+1:]
        #elif i > 0 and RLE[i][0]  == RLE[i-1][0]:
        #    RLE = RLE[:i-1] + [ [RLE[i][0], RLE[i-1][1]+RLE[i][1]] ] + RLE[i+1:]

        return RLE

    def writeRLE(self, vector, filehandle):
        val = vector[0]
        length = 0

        for v in vector:
            if v == val:
                length += 1
            else:
                if length == 1:
                    filehandle.write(str(val) + '\n')
                else:
                    filehandle.write(str(val) + '\t' + str(length) + '\n')
                val = v
                length = 1

        if length == 1:
            filehandle.write(str(val) + '\n')
        else:
            filehandle.write(str(val) + '\t' + str(length) + '\n')

        