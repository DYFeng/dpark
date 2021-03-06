import bisect

from dpark.util import portable_hash
from dpark.serialize import load_func, dump_func
import weakref
class Dependency:
    def __init__(self, rdd):
        self.rdd = weakref.proxy(rdd)

    def __getstate__(self):
        raise ValueError("Should not pickle dependency: %r" % self)

class NarrowDependency(Dependency):
    isShuffle = False
    def getParents(self, outputPartition):
        raise NotImplementedError

class OneToOneDependency(NarrowDependency):
    def getParents(self, pid):
        return [pid]

class OneToRangeDependency(NarrowDependency):
    def __init__(self, rdd, splitSize, length):
        Dependency.__init__(self, rdd)
        self.splitSize = splitSize
        self.length = length

    def getParents(self, pid):
        return range(pid * self.splitSize,
                min((pid+1) * self.splitSize, self.length))

class CartesianDependency(NarrowDependency):
    def __init__(self, rdd, first, numSplitsInRdd2):
        NarrowDependency.__init__(self, rdd)
        self.first = first
        self.numSplitsInRdd2 = numSplitsInRdd2

    def getParents(self, pid):
        if self.first:
            return [pid / self.numSplitsInRdd2]
        else:
            return [pid % self.numSplitsInRdd2]

class RangeDependency(NarrowDependency):
    def __init__(self, rdd, inStart, outStart, length):
        Dependency.__init__(self, rdd)
        self.inStart = inStart
        self.outStart = outStart
        self.length = length

    def getParents(self, pid):
        if pid >= self.outStart and pid < self.outStart + self.length:
            return [pid - self.outStart + self.inStart]
        return []

class ShuffleDependency(Dependency):
    isShuffle = True
    def __init__(self, shuffleId, rdd, aggregator, partitioner):
        Dependency.__init__(self, rdd)
        self.shuffleId = shuffleId
        self.aggregator = aggregator
        self.partitioner = partitioner


class Aggregator:
    def __init__(self, createCombiner, mergeValue,
            mergeCombiners):
        self.createCombiner = createCombiner
        self.mergeValue = mergeValue
        self.mergeCombiners = mergeCombiners

    def __getstate__(self):
        return (dump_func(self.createCombiner),
            dump_func(self.mergeValue),
            dump_func(self.mergeCombiners))

    def __setstate__(self, state):
        c1, c2, c3 = state
        self.createCombiner = load_func(c1)
        self.mergeValue = load_func(c2)
        self.mergeCombiners = load_func(c3)

class AddAggregator:
    def createCombiner(self, x):
        return x
    def mergeValue(self, s, x):
        return s + x
    def mergeCombiners(self, x, y):
        return x + y

class MergeAggregator:
    def createCombiner(self, x):
        return [x]
    def mergeValue(self, s, x):
        s.append(x)
        return s
    def mergeCombiners(self, x, y):
        x.extend(y)
        return x

class UniqAggregator:
    def createCombiner(self, x):
        return set([x])
    def mergeValue(self, s, x):
        s.add(x)
        return s
    def mergeCombiners(self, x, y):
        x |= y
        return x

class Partitioner:
    @property
    def numPartitions(self):
        raise NotImplementedError
    def getPartition(self, key):
        raise NotImplementedError

class HashPartitioner(Partitioner):
    def __init__(self, partitions):
        self.partitions = max(1, int(partitions))
        
    @property
    def numPartitions(self):
        return self.partitions

    def getPartition(self, key):
        return portable_hash(key) % self.partitions

    def __eq__(self, other):
        if isinstance(other, Partitioner):
            return other.numPartitions == self.numPartitions
        return False

class RangePartitioner(Partitioner):
    def __init__(self, keys, reverse=False):
        self.keys = sorted(keys)
        self.reverse = reverse

    @property
    def numPartitions(self):
        return len(self.keys) + 1

    def getPartition(self, key):
        idx = bisect.bisect(self.keys, key)
        return len(self.keys) - idx if self.reverse else idx

    def __eq__(self, other):
        if isinstance(other, RangePartitioner):
            return other.keys == self.keys and self.reverse == other.reverse
        return False
