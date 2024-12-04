import re
import gc
import numpy as np
import unittest
from unittest.mock import patch
from numba.cuda.runtime import rtsys
from numba.tests.support import EnableNRTStatsMixin
from numba.cuda.testing import CUDATestCase

from numba.cuda.tests.nrt.mock_numpy import cuda_empty, cuda_empty_like

from numba import cuda


class TestNrtRefCt(EnableNRTStatsMixin, CUDATestCase):

    def setUp(self):
        # Clean up any NRT-backed objects hanging in a dead reference cycle
        gc.collect()
        super(TestNrtRefCt, self).setUp()

    def test_no_return(self):
        """
        Test issue #1291
        """
        n = 10

        @cuda.jit(debug=True)
        def kernel():
            for i in range(n):
                temp = cuda_empty(2, np.float64) # noqa: F841
            return None

        init_stats = rtsys.get_allocation_stats()
        print("init_stats", init_stats)

        with patch('numba.config.CUDA_ENABLE_NRT', True, create=True):
            kernel[1,1]()
        print("After kernel launch...")
        cur_stats = rtsys.get_allocation_stats()
        print("cur_stats", cur_stats)
        self.assertEqual(cur_stats.alloc - init_stats.alloc, n)
        self.assertEqual(cur_stats.free - init_stats.free, n)

    def test_escaping_var_init_in_loop(self):
        """
        Test issue #1297
        """

        @cuda.jit
        def g(n):

            x = cuda_empty((n, 2), np.float64)

            for i in range(n):
                y = x[i]

            for i in range(n):
                y = x[i] # noqa: F841

            return None

        init_stats = rtsys.get_allocation_stats()
        print("init_stats", init_stats)
        with patch('numba.config.CUDA_ENABLE_NRT', True, create=True):
            g[1, 1](10)
        print("After kernel launch...")
        cur_stats = rtsys.get_allocation_stats()
        print("cur_stats", cur_stats)
        self.assertEqual(cur_stats.alloc - init_stats.alloc, 1)
        self.assertEqual(cur_stats.free - init_stats.free, 1)

    def test_invalid_computation_of_lifetime(self):
        """
        Test issue #1573
        """
        @cuda.jit
        def if_with_allocation_and_initialization(arr1, test1):
            tmp_arr = cuda_empty_like(arr1)

            for i in range(tmp_arr.shape[0]):
                pass

            if test1:
                cuda_empty_like(arr1)

        arr = np.random.random((5, 5))  # the values are not consumed

        init_stats = rtsys.get_allocation_stats()
        with patch('numba.config.CUDA_ENABLE_NRT', True, create=True):
            if_with_allocation_and_initialization[1, 1](arr, False)
        cur_stats = rtsys.get_allocation_stats()
        self.assertEqual(cur_stats.alloc - init_stats.alloc,
                         cur_stats.free - init_stats.free)

    def test_del_at_beginning_of_loop(self):
        """
        Test issue #1734
        """
        @cuda.jit
        def f(arr):
            res = 0

            for i in (0, 1):
                # `del t` is issued here before defining t.  It must be
                # correctly handled by the lowering phase.
                t = arr[i]
                if t[i] > 1:
                    res += t[i]

        arr = np.ones((2, 2))
        init_stats = rtsys.get_allocation_stats()
        with patch('numba.config.CUDA_ENABLE_NRT', True, create=True):
            f[1, 1](arr)
        cur_stats = rtsys.get_allocation_stats()
        self.assertEqual(cur_stats.alloc - init_stats.alloc,
                         cur_stats.free - init_stats.free)


class TestNrtBasic(CUDATestCase):
    def test_nrt_launches(self):
        @cuda.jit
        def f(x):
            return x[:5]

        @cuda.jit
        def g():
            x = cuda_empty(10, np.int64)
            f(x)

        with patch('numba.config.CUDA_ENABLE_NRT', True, create=True):
            g[1,1]()
        cuda.synchronize()

    def test_nrt_ptx_contains_refcount(self):
        @cuda.jit
        def f(x):
            return x[:5]

        @cuda.jit
        def g():
            x = cuda_empty(10, np.int64)
            f(x)

        with patch('numba.config.CUDA_ENABLE_NRT', True, create=True):
            g[1,1]()

        ptx = next(iter(g.inspect_asm().values()))

        # The following checks that a `call` PTX instruction is
        # emitted for NRT_MemInfo_alloc_aligned, NRT_incref and
        # NRT_decref
        p1 = r"call\.uni(.|\n)*NRT_MemInfo_alloc_aligned"
        match = re.search(p1, ptx)
        assert match is not None

        p2 = r"call\.uni.*\n.*NRT_incref"
        match = re.search(p2, ptx)
        assert match is not None

        p3 = r"call\.uni.*\n.*NRT_decref"
        match = re.search(p3, ptx)
        assert match is not None

    def test_nrt_returns_correct(self):
        @cuda.jit
        def f(x):
            return x[5:]

        @cuda.jit
        def g(out_ary):
            x = cuda_empty(10, np.int64)
            x[5] = 1
            y = f(x)
            out_ary[0] = y[0]

        out_ary = np.zeros(1, dtype=np.int64)

        with patch('numba.config.CUDA_ENABLE_NRT', True, create=True):
            g[1,1](out_ary)

        self.assertEqual(out_ary[0], 1)


if __name__ == '__main__':
    unittest.main()
