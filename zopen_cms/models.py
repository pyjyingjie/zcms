# -*- encoding: utf-8 -*-

__docformat__ = 'restructuredtext'

import time
import tempfile
import os.path
import stat
import posixpath

def get_sub_time_paths(folder, root_vpath):
    """ 迭代查找整个子目录，找出所有的子文档的路径 """

    result = []
    for obj in folder.values(True, False):
        dc = obj.metadata
        if isinstance(obj, Folder):
            result.extend(get_sub_time_paths(obj, root_vpath))
        elif isinstance(obj, Document):
            result.append((
                dc.get('modified', 
                dc.get('created', '')),
                obj.vpath.replace(root_vpath + '/', ''),
            ))
    return result



class FRSAsset(object):

    __parent__ = None
    __name__ = ''

    def __init__(self, frs, vpath=u'/'):
        self.frs = frs
        self.vpath = vpath
        self._md = None

    @property
    def ospath(self):
        return self.frs.ospath(self.vpath)

    @property
    def metadata(self):
        if self._md is None:
            self._md = self.frs.getMetadata(self.vpath) or {}
        return self._md

    @property
    def title(self):
        return self.metadata.get('title', '') or self.__name__


class Folder(FRSAsset):

    def _filter(self, key):
        """Subclasses may overwrite this method.

        Filter possible assets.
        """
        return (not key.startswith('.'))

    def _get(self, key):
        key = key.encode('utf-8')  # key is unicode by default

        if not self._filter(key):
            raise KeyError(key)

        try:
            path = self.frs.joinpath(self.vpath, key)
            st = self.frs.stat(path)
        except OSError:
            raise KeyError(key)

        if stat.S_ISDIR(st.st_mode):
            obj = Folder(self.frs, path)
        elif stat.S_ISREG(st.st_mode):
            ext = posixpath.splitext(path)[1].lower()
            if ext in ['.gif', '.bmp', '.jpg', '.jpeg', '.png']:
                obj = Image(self.frs, path)
            elif ext in ['.html', '.htm', '.rst']:
                obj = Document(self.frs, path)
            else:
                obj = File(self.frs, path)
        else:
            raise KeyError(key)

        obj.__parent__ = self
        obj.__name__ = key
        return obj

    def keys(self, do_filter=False, do_sort=False):
        if self.vpath is None:
            return []

        keys = sorted([
            unicode(key) for key in self.frs.listdir(self.vpath)
            if self._filter(key)
        ])

        if not do_filter and not do_sort:
            return keys

        metadata = self.metadata

        if do_filter:
            hidden_keys = metadata.get('hidden_keys', [])
            if hidden_keys:
                keys = [key for key in keys if key not in hidden_keys]
                # 通配后缀隐藏
                tmp_keys = keys[:]
                for hkey in [key for key in hidden_keys if key.startswith('*')]:
                    for key1 in tmp_keys:
                        if key1.endswith(hkey[1:]):
                            keys.remove(key1)
            # 通配类型隐藏
            hidden_types = metadata.get('hidden_types', [])
            if hidden_types:
                tmp_keys = keys[:]
                for type in hidden_types:
                    for key in tmp_keys:
                        sub_file = self.get_obj_by_subpath(key)
                        sub_metadata = sub_file.metadata
                        sub_type = sub_metadata.get('contenttype', '')
                        if type == sub_type:
                            keys.remove(key)

        if do_sort:
            sorted_keys = metadata.get('keys', [])
            if sorted_keys:
                sorted_keys.reverse()
                for key in sorted_keys:
                    try:
                        keys.remove(key)
                        keys.insert(0, key)
                    except ValueError:
                        # wrong key in config file
                        pass
        return keys

    def get(self, key, default=None):
        try:
            return self._get(key)
        except KeyError:
            return default

    def values(self, do_filter=False, do_sort=False):
        return [self._get(key) for key in self.keys(do_filter, do_sort)]

    def items(self, do_filter=False, do_sort=False):
        return [(key, self._get(key)) for key in self.keys(do_filter, do_sort)]

    def get_recent_file_subpaths(self):
        # 1. 检查是否存在有效的缓存，如果有，直接返回sub_vpath清单
        # ['asdfa/aa.doc', 'asdf.rst']
        #today_str = datetime.date.today().strftime('%Y-%m-%d')
        timenow = [t for t in time.localtime(time.time())[:5]]
        str_timenow = '-'.join(
            [str(t) for t in time.localtime(time.time())[:5]])

        tmp_dir = tempfile.gettempdir()
        cache_name = 'zcmscache' + '-'.join(self.vpath.split('/'))
        cache_path = os.path.join(tmp_dir, cache_name) + '.txt'
        sub_vpaths = []
        cache_is_recent = False
        minutes_lag = 720  # 默认半天

        def lag_minutes(time_now, txt_time):
            tn, tt = time_now[:], txt_time[:]
            to_expend = [0, 0, 75, 0]
            for t in to_expend:
                tn.append(t)
                tt.append(t)
            t1 = time.mktime(tn)
            t2 = time.mktime(tt)
            lag = (t1 - t2) / 60
            return lag

        # try the cache first
        if os.path.exists(cache_path):
            rf = file(cache_path, 'r')
            txt_date = rf.readline().rstrip()
            if txt_date != '':
                txt_time = [int(n) for n in txt_date.split('-')]
                if lag_minutes(timenow, txt_time) < minutes_lag:
                    cache_is_recent = True
                    sub_vpaths = [rl.rstrip() for rl in rf.readlines()]
            rf.close()

        # 2. 否则重新查找出来，并更新缓存
        if not cache_is_recent:
            wf = file(cache_path, 'w')
            to_write = str_timenow + '\n'

            sub_time_vpaths = get_sub_time_paths(self, self.vpath)

            def mycmp(x, y):
                if x[0] == '' or y[0] == '':
                    return -1
                return cmp(y[0], x[0])

            # todo
            sub_time_vpaths.sort(mycmp)
            sub_vpaths = [vpath[1] for vpath in sub_time_vpaths]

            for vpath in sub_vpaths:
                to_write += vpath + '\n'
            wf.write(to_write)
            wf.close()
        return sub_vpaths

    def get_obj_by_subpath(self, sub_vpath):
        """ 根据vpath，找到对象 """
        cur = self
        for name in sub_vpath.split('/'):
            if not name:
                pass
            cur = cur.get(name)
        return cur

    def __getitem__(self, key):
        """ traverse """
        return self._get(key)

    def __contains__(self, key):
        return key in self.keys()

    def __iter__(self):
        return iter(self.keys())

    def __len__(self):
        return len(self.keys())


class File(FRSAsset):

    def _get_data(self):
        if self.vpath is None:
            return ''
        else:
            return self.frs.open(self.vpath, 'rb').read()

    def _set_data(self, value):
        if self.vpath is None:
            raise NotImplementedError('Choose first a valid path.')
        else:
            self.frs.open(self.vpath, 'wb').write(value)

    data = property(_get_data, _set_data)

    @property
    def contentType(self):
        if self.vpath.endswith('html'):
            return 'text/html'
        elif self.vpath.endswith('rst'):
            return 'text/rst'
        else:
            return 'text/plain'


class Document(File):
    pass


class Image(File):
    pass
