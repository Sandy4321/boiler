#! /usr/bin/env python3
import alignments
import re
import read
import pairedread
import junction
import bisect
import binaryIO
import math

import random
import inspect

import huffman

import os

class Compressor:
    aligned = None

    sectionLen = 100000
    exonChunkSize = 100
    junctionChunkSize = 50

    # 0 - zlib
    # 1 - lzma
    # 2 - bz2
    compressMethod = 0

    def __init__(self):   
        if self.compressMethod == 0:
            self.zlib = __import__('zlib')
        elif self.compressMethod == 1:
            self.lzma = __import__('lzma')
        elif self.compressMethod == 2:
            self.bz2 = __import__('bz2')

    def compress(self, samFilename, compressedFilename, binary=False, huffman=False):
        ''' Compresses the alignments to 2 files, one for unspliced and one for spliced

            file_prefix: Prefix for all output file names
        '''

        self.huffman = huffman

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

        self.parseAlignments(samFilename)

        #print(self.aligned.chromOffsets['3L'])
        #for i in range(len(self.aligned.exons)):
        #    if abs(self.aligned.exons[i] - self.aligned.chromOffsets['3L'] - 15897967) < 10:
        #        print(i)
        #        print(self.aligned.exons[i])
        #        print(self.aligned.exons[i+1])
        #        break
        #exit()

        ''' TODO: No need for if/else? '''
        if binary:
            with open(compressedFilename, 'wb') as f:
                s = binaryIO.writeChroms(self.aligned.chromosomes)
                f.write(s)
                s, self.exonBytes = binaryIO.writeExons(self.aligned.exons)
                f.write(s)
                
                junctions, maxReadLen = self.computeJunctions()
                self.compressUnspliced(f, binary)
                self.compressSpliced(junctions, maxReadLen, f, binary)
            
            # Write exons and index information
            compressed = None
            with open(compressedFilename, 'rb') as f:
                compressed = f.read()
            with open(compressedFilename, 'wb') as f:
                self.writeIndexBinary(f)
                f.write(compressed)

        else:
            with open(compressedFilename, 'w') as f:
                if len(self.aligned.spliced) > 0:
                    junctions, maxReadLen = self.computeJunctions()
                    self.compressSpliced(junctions, maxReadLen, f, binary)
                f.write('/\n')
                if len(self.aligned.unspliced) > 0:
                    self.compressUnspliced(f, binary)

            with open(compressedFilename, 'r') as f:
                compressed = f.read()
            with open(compressedFilename, 'w') as f:
                chroms = []
                for k,v in self.aligned.chromosomes.items():
                    chroms.append(str(k)+','+str(v))
                f.write('\t'.join(chroms) + '\n')

                f.write('\t'.join([str(e) for e in self.aligned.exons]) + '\n')

                f.write(compressed)

        '''
        self.parseAlignments(samFilename)
        
        if binary:
            # Write spliced and unspliced information
            with open(compressedFilename, 'wb') as f:                
                s = binaryIO.writeChroms(self.aligned.chromosomes)
                f.write(s)
                s, self.exonBytes = binaryIO.writeExons(self.aligned.exons)
                f.write(s)

                junctions, maxReadLen = self.computeJunctions()

                self.compressUnspliced(f, binary)

                self.compressSpliced(junctions, maxReadLen, f, binary)
            
            # Write exons and index information
            compressed = None
            with open(compressedFilename, 'rb') as f:
                compressed = f.read()
            with open(compressedFilename, 'wb') as f:
                self.writeIndexBinary(f)
                f.write(compressed)
        
        else:
            # Write exons and index information
            #compressed = None
            #with open(compressedFilename, 'r') as f:
            #    compressed = f.read()
            with open(compressedFilename, 'w') as f:
                chroms = []
                for k,v in self.aligned.chromosomes.items():
                    chroms.append(str(k)+','+str(v))
                f.write('\t'.join(chroms) + '\n')

                f.write('\t'.join([str(e) for e in self.aligned.exons]) + '\n')

                #self.writeIndex(f)
                #f.write(compressed)

                if len(self.aligned.spliced) > 0:
                    junctions, maxReadLen = self.computeJunctions()
                    self.compressSpliced(junctions, maxReadLen, f, binary)

                f.write('/\n')

                if len(self.aligned.unspliced) > 0:
                    self.compressUnspliced(f, binary)
        '''

    def computeJunctions(self):
        # Compute coverage levels across every exon junction
        junctions = dict()

        # Keep track of maximum read and fragment lengths
        maxReadLen = 0

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
                j.coverage = self.updateRLE(j.coverage, r.startOffset, j.length-r.endOffset-r.startOffset, 1)

                #for i in range(r.startOffset, len(j.coverage)-r.endOffset):
                #    j.coverage[i] += 1
            else:
                j.coverage = self.updateRLE(j.coverage, r.startOffset, r.lenLeft, 1)
                j.coverage = self.updateRLE(j.coverage, j.length-r.endOffset-r.lenRight, r.lenRight, 1)

                #for i in range(r.startOffset, r.startOffset+r.lenLeft):
                #    j.coverage[i] += 1
                #for i in range(len(j.coverage)-r.endOffset-r.lenRight, len(j.coverage)-r.endOffset):
                #    j.coverage[i] += 1


            # If this is a paired read, lenLeft and lenRight are both > 0
            if r.lenLeft > 0 or r.lenRight > 0:
                # update pairedLens
                if r.readLen in j.pairedLens:
                    j.pairedLens[r.readLen] += 1
                else:
                    j.pairedLens[r.readLen] = 1

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
            else:
                # update unpairedLens
                if r.readLen in j.unpairedLens:
                    j.unpairedLens[r.readLen] += 1
                else:
                    j.unpairedLens[r.readLen] = 1

                if r.readLen > maxReadLen:
                    maxReadLen = r.readLen

        # Compute difference run-length encoding for junctions and update huffman index
        if self.huffman:
            self.huffmanFreqs = dict()

            for j in junctions.values():
                j.differenceEncode()

                # Increment huffman frequencies
                for row in j.covDRLE:
                    if row[0] in self.huffmanFreqs:
                        self.huffmanFreqs[row[0]] += 1
                    else:
                        self.huffmanFreqs[row[0]] = 1

        return junctions, maxReadLen


    def compressSpliced(self, junctions, maxReadLen, filehandle, binary=False):
        ''' Compress the spliced alignments to a single file

            filehandle: File to write to
        '''

        #print('Writing junctions')
        #print('Junctions length: %f' % (asizeof.asizeof(junctions)/1000000))

        if binary:
            # Determine the number of bytes for read lengths
            readLenBytes = binaryIO.findNumBytes(maxReadLen)
            binaryIO.writeVal(filehandle, 1, readLenBytes)

        # Junction index: list of junctions and length of each chunk
        self.sortedJuncs = sorted(junctions.keys(), key=lambda x: [int(n) for n in x.split('\t')[:-2]])
        self.junctionChunkLens = [0] * int(math.ceil(len(self.sortedJuncs) / self.junctionChunkSize))

        i = 0
        s = b''
        chunkId = 0
        for key in self.sortedJuncs:
            i += 1

            junc = junctions[key]

            if binary:
                if self.huffman:
                    s += binaryIO.writeJunction(readLenBytes, junc, self.huffmanIndex)
                else:
                    s += binaryIO.writeJunction(readLenBytes, junc)

                if i == self.junctionChunkSize:
                    start = filehandle.tell()

                    # Write to file
                    filehandle.write(self.compressString(s))

                    # save length of chunk in file to index
                    self.junctionChunkLens[chunkId] = filehandle.tell()-start
                    chunkId += 1

                    i = 0
                    s = b''
            else:
                # write junction information
                filehandle.write('>' + key + '\n')

                # write read lengths
                filehandle.write('\t'.join( [str(k)+','+str(v) for k,v in junc.unpairedLens.items()] ) + '\n')
                filehandle.write('\t'.join( [str(k)+','+str(v) for k,v in junc.pairedLens.items()] ) + '\n')

                # Write left and right read lengths
                filehandle.write('\t'.join([str(k)+','+str(v) for k,v in junc.lensLeft.items()]) + '\n')
                filehandle.write('\t'.join([str(k)+','+str(v) for k,v in junc.lensRight.items()]) + '\n')

                # write coverage
                self.writeRLE(junc.coverage, filehandle)
        if binary and i > 0:
            # Write final junctions
            start = filehandle.tell()

            # Write to file
            filehandle.write(self.compressString(s))

            # save length of chunk in file to index
            self.junctionChunkLens[chunkId] = filehandle.tell()-start


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
                if r.lenLeft == 0 and r.lenRight == 0:
                    if r.readLen > maxReadLen:
                        maxReadLen = r.readLen
                else:
                    if r.lenLeft > maxReadLen:
                        maxReadLen = r.lenLeft
                    if r.lenRight > maxReadLen:
                        maxReadLen = r.lenRight
                    if r.readLen > maxFragLen:
                        maxFragLen = r.readLen

            if not r.NH in readExons:
                readExons[r.NH] = []
                for n in range(len(self.aligned.exons)-1):
                    readExons[r.NH] += [[]]


                #print('Adding NH = %d' % r.NH)
                #print('  Coverages size: %f' % (asizeof.asizeof(coverages)/1000000))
                if r.NH == 1:
                    coverages[r.NH] = [0] * self.aligned.exons[-1]
                else:
                    coverages[r.NH] = [ [0, self.aligned.exons[-1]] ]


            j = bisect.bisect_right(self.aligned.exons, r.exons[0][0])-1
            readExons[r.NH][j] += [len(self.aligned.unspliced) - i - 1]

            if r.NH == 1:
                # update coverage vector
                if (r.lenLeft == 0 and r.lenRight == 0):
                    for n in range(r.exons[0][0], r.exons[0][1]):
                        coverages[r.NH][n] += 1
                else:
                    for n in range(r.exons[0][0], r.exons[0][0]+r.lenLeft):
                        coverages[r.NH][n] += 1
                    for n in range(r.exons[0][1]-r.lenRight, r.exons[0][1]):
                        coverages[r.NH][n] += 1
            else:
                # update coverage vector
                if (r.lenLeft == 0 and r.lenRight == 0):
                    coverages[r.NH] = self.updateRLE(coverages[r.NH], r.exons[0][0], r.exons[0][1]-r.exons[0][0], 1)
                else:
                    coverages[r.NH] = self.updateRLE(coverages[r.NH], r.exons[0][0], r.lenLeft, 1)
                    coverages[r.NH] = self.updateRLE(coverages[r.NH], r.exons[0][1]-r.lenRight, r.lenRight, 1)

        coverages[1] = self.RLE(coverages[1])

        # Compute difference run-length encoding for junctions and update huffman index
        if self.huffman:
            for cov in coverages.values():
                # Add first value
                if cov[0][0] in self.huffmanFreqs:
                    self.huffmanFreqs[cov[0][0]] += 1
                else:
                    self.huffmanFreqs[cov[0][0]] = 1

                for i in range(1,len(cov)):
                    val = cov[i][0] - cov[i-1][0]
                    cov[i][0] = val
                    if val in self.huffmanFreqs:
                        self.huffmanFreqs[val] += 1
                    else:
                        self.huffmanFreqs[val] = 1

            # Create huffman index from frequencies
            freqs = [(k,v) for k,v in self.huffmanFreqs.items()]
            self.huffmanIndex = huffman.createHuffmanIndex(freqs)

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
                    unpairedLens = dict()
                    pairedLens = dict()

                    # Distribution of all gap lengths in paired-end reads
                    lensLeft = dict()
                    lensRight = dict()

                    for readId in reads[i]:
                        read = self.aligned.unspliced[readId]
                        alignment = read.exons

                        # update left and right read lengths
                        if read.lenLeft > 0 or read.lenRight > 0:
                            # update read lengths distribution
                            length = alignment[0][1] - alignment[0][0]
                            if length in pairedLens:
                                pairedLens[length] += 1
                            else:
                                pairedLens[length] = 1

                            if read.lenLeft in lensLeft:
                                lensLeft[read.lenLeft] += 1
                            else:
                                lensLeft[read.lenLeft] = 1

                            if read.lenRight in lensRight:
                                lensRight[read.lenRight] += 1
                            else:
                                lensRight[read.lenRight] = 1
                        else:
                            # update read lengths distribution
                            length = alignment[0][1] - alignment[0][0]
                            if length in unpairedLens:
                                unpairedLens[length] += 1
                            else:
                                unpairedLens[length] = 1

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
            offsets = [0] * len(breakpoints)

            pos = 0
            currBreakpoint = 0
            start = filehandle.tell()
            segmentRLE = []
            for c in cov:
                segmentEnd = pos+c[1]
                while currBreakpoint < len(breakpoints)-1 and breakpoints[currBreakpoint+1] <= segmentEnd:
                    length = breakpoints[currBreakpoint+1] - pos
                    if length > 0:
                        segmentRLE.append([c[0], length])
                    
                    if len(segmentRLE) == 1 and segmentRLE[0][0] == 0:
                        offsets[currBreakpoint] = 0
                    else:
                        if self.huffman:
                            s = binaryIO.writeCovHuffman(segmentRLE, self.huffmanIndex)
                        else:
                            s = binaryIO.writeCov(segmentRLE)
                        filehandle.write(self.compressString(s))
                        offsets[currBreakpoint] = filehandle.tell() - start
                    currBreakpoint += 1
                    segmentRLE = []

                    c[1] -= length
                    pos += length
                    start = filehandle.tell()

                if c[1] > 0:
                    segmentRLE.append(c)
                    pos += c[1]
            if len(segmentRLE) > 0:
                if len(segmentRLE) == 1 and segmentRLE[0][0] == 0:
                    offsets[currBreakpoint] = 0
                else:
                    if self.huffman:
                        s += binaryIO.writeCovHuffman(segmentRLE, self.huffmanIndex)
                    else:
                        s = binaryIO.writeCov(segmentRLE)
                    filehandle.write(self.compressString(s))
                    offsets[currBreakpoint] = filehandle.tell() - start

            self.unsplicedIndex[NH] = offsets


            # Write lengths for each exon
            exonsIndex = []
            chunkId = 0
            chunkString = b''
            for i in range(len(reads)):
                chunkId += 1

                # Distribution of all read lengths
                unpairedLens = dict()
                pairedLens = dict()

                # Distribution of all gap lengths in paired-end reads
                lensLeft = dict()
                lensRight = dict()

                for readId in reads[i]:
                    read = self.aligned.unspliced[readId]
                    #alignment = read.exons

                    # update left and right read lengths
                    if read.lenLeft > 0 or read.lenRight > 0:
                        # update paired read lengths distribution
                        length = read.readLen
                        if length in pairedLens:
                            pairedLens[length] += 1
                        else:
                            pairedLens[length] = 1

                        if read.lenLeft in lensLeft:
                            lensLeft[read.lenLeft] += 1
                        else:
                            lensLeft[read.lenLeft] = 1

                        if read.lenRight in lensRight:
                            lensRight[read.lenRight] += 1
                        else:
                            lensRight[read.lenRight] = 1
                    else:
                        # update unpaired read lengths distribution
                        length = read.readLen
                        if length in unpairedLens:
                            unpairedLens[length] += 1
                        else:
                            unpairedLens[length] = 1

                chunkString += binaryIO.writeLens(readLenBytes, unpairedLens)
                chunkString += binaryIO.writeLens(fragLenBytes, pairedLens)
                if len(pairedLens) > 0:
                    chunkString += binaryIO.writeLens(readLenBytes, lensLeft)
                    if len(lensLeft) > 0:
                        chunkString += binaryIO.writeLens(readLenBytes, lensRight)

                if chunkId == self.exonChunkSize or i == len(reads)-1:
                    startPos = filehandle.tell()
                    filehandle.write(self.compressString(chunkString))
                    exonsIndex.append(filehandle.tell() - startPos)
                    chunkId = 0
                    chunkString = b''

            self.unsplicedExonsIndex[NH] = exonsIndex
    
    def parseAlignments(self, filename, offset=0):
        ''' Parse a file in SAM format
            Add the exonic region indices for each read to the correct ChromosomeAlignments object
            
            filehandle: SAM filehandle containing aligned reads
        '''

        with open(filename, 'r') as filehandle:
            for line in filehandle:
                row = line.strip().split('\t')
                if len(row) < 5:
                    continue

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
                        pair_chrom = row[2]
                    else:
                        pair_chrom = row[6]
                    pair_index = int(row[7])

                    self.aligned.processRead(read.Read(row[2], exons, xs, NH), pair_chrom, pair_index)
                else:
                    self.aligned.processRead(read.Read(row[2], exons, xs, NH))

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
                rle.append([val, length])
                val = v
                length = 1

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
        ''' Write vector that is already run-length encoded '''
        for v in vector:
            if v[1] == 1:
                filehandle.write(str(v[0]) + '\n')
            else:
                filehandle.write(str(v[0]) + '\t' + str(v[1]) + '\n')

    def writeIndex(self, f):
        # Write junctions index
        f.write(bytes('#' + str(self.exonChunkSize) + '\n', 'UTF-8'))
        f.write(bytes('#' + ' '.join([str(k)+','+str(v) for (k,v) in self.junctionIndex]) + '\n', 'UTF-8'))

        for k,v in self.unsplicedIndex.items():
            # Write unspliced coverage index
            f.write(bytes('#' + str(k) + '\t' + '\t'.join([str(i) for i in v]) + '\n', 'UTF-8'))
        
            # Write unspliced exon reads index
            f.write(bytes('#' + str(k) + '\t' + '\t'.join([str(i) for i in self.unsplicedExonsIndex[k]]) + '\n', 'UTF-8'))

    def writeIndexBinary(self, f):
        s = binaryIO.valToBinary(4, self.exonChunkSize)
        s += binaryIO.valToBinary(4, self.junctionChunkSize)

        # Write junction names
        s += binaryIO.writeJunctionsList(self.sortedJuncs, self.exonBytes)

        # Write length of junction chunks
        s += binaryIO.writeList(self.junctionChunkLens)

        # Number of NH values
        s += binaryIO.valToBinary(4, len(self.unsplicedIndex.items()))
        for k in self.unsplicedIndex.keys():
            # NH value
            s += binaryIO.valToBinary(4, k)

            # Write unspliced coverage index
            s += binaryIO.writeList(self.unsplicedIndex[k])
        
            # Write unspliced exon reads index
            s += binaryIO.writeList(self.unsplicedExonsIndex[k])

        # Write huffman index
        if self.huffman:
            s += binaryIO.writeHuffmanIndex(self.huffmanIndex)

        # Compress and write to file
        s = self.compressString(s)
        binaryIO.writeVal(f, 4, len(s))
        f.write(s)

    def compressString(self, s):
        ''' Use a predefined python library to compress the given string.
            Return the compressed string '''

        if self.compressMethod == 0:
            return self.zlib.compress(s)
        elif self.compressMethod == 1:
            return self.lzma.compress(s)
        elif self.compressMethod == 2:
            return self.bz2.compress(s)

        
