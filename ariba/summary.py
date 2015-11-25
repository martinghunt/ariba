import os
import openpyxl
import pyfastaq
from ariba import flag, common

class Error (Exception): pass

columns = [
    'gene',
    'flag',
    'reads',
    'cluster',
    'gene_len',
    'assembled',
    'pc_ident',
    'var_type',
    'var_effect',
    'new_aa',
    'gene_start',
    'gene_end',
    'gene_nt',
    'scaffold',
    'scaff_len',
    'scaff_start',
    'scaff_end',
    'scaff_nt',
    'read_depth',
    'alt_bases',
    'ref_alt_depth'
]

int_columns = [
    'reads',
    'gene_len',
    'assembled',
    'gene_start',
    'gene_end',
    'scaff_len',
    'scaff_start',
    'scaff_end',
    'read_depth',
]


class Summary:
    def __init__(
      self,
      outfile,
      filenames=None,
      fofn=None,
      filter_output=True,
      js_candy_prefix=None,
      min_id=90.0
    ):
        if filenames is None and fofn is None:
            raise Error('Error! Must supply filenames or fofn to Summary(). Cannot continue')

        if filenames is None:
            self.filenames = []
        else:
            self.filenames = filenames

        if fofn is not None:
            self.filenames.extend(self._load_fofn(fofn))

        self.filter_output = filter_output
        self.min_id = min_id
        self.outfile = outfile
        self.js_candy_prefix = js_candy_prefix


    def _load_fofn(self, fofn):
        f = pyfastaq.utils.open_file_read(fofn)
        filenames = [x.rstrip() for x in f.readlines()]
        pyfastaq.utils.close(f)
        return filenames


    def _check_files_exist(self):
        for fname in self.filenames:
            if not os.path.exists(fname):
                raise Error('File not found: "' + fname + '". Cannot continue')


    def _line2dict(self, line):
        data = line.rstrip().split('\t')
        d = {columns[i]: data[i] for i in range(len(data))}
        d['flag'] = flag.Flag(int(d['flag']) )
        for key in int_columns:
            try:
                d[key] = int(d[key])
            except:
                assert d[key] == '.'
        try:
            d['pc_ident'] = float(d['pc_ident'])
        except:
            assert d['pc_ident'] == '.'
        return d


    def _load_file(self, filename):
        f = pyfastaq.utils.open_file_read(filename)
        d = {}

        for line in f:
            if line.startswith('#'):
                if line.rstrip()[1:].split('\t') != columns:
                    raise Error('Error parsing the following line.\n' + line)
                continue
            data = self._line2dict(line)

            if data['gene'] not in d:
                d[data['gene']] = []

            d[data['gene']].append(data)

        pyfastaq.utils.close(f)
        return d


    def _to_summary_number(self, l):
        f = l[0]['flag']
        if f.has('assembly_fail') or not f.has('gene_assembled') or self._pc_id_of_longest(l) <= self.min_id:
            return 0

        if f.has('hit_both_strands') or (not f.has('complete_orf')):
            return 1

        if f.has('unique_contig') and f.has('gene_assembled_into_one_contig') and f.has('complete_orf'):
            if f.has('has_nonsynonymous_variants'):
                return 3
            else:
                return 4
        else:
            return 2


    def _pc_id_of_longest(self, l):
        longest = 0
        identity = None
        for data in l:
            if data['assembled'] > longest:
                longest = data['assembled']
                identity = data['pc_ident']

        assert identity is not None
        return identity



    def _gather_output_rows(self):
        self.data = {filename: self._load_file(filename) for filename in self.filenames}

        all_genes = set()
        for l in self.data.values():
            all_genes.update(set(l.keys()))
        all_genes = list(all_genes)
        all_genes.sort()

        self.rows_out = []
        self.rows_out.append(['filename'] + all_genes)

        for filename in self.filenames:
            new_row = [filename]
            for gene in all_genes:
                if gene not in self.data[filename]:
                    new_row.append(0)
                else:
                    new_row.append(self._to_summary_number(self.data[filename][gene]))

            self.rows_out.append(new_row)


    def _filter_output_rows(self):
        if not self.filter_output:
            return

        # remove rows that are all zeros
        self.rows_out = [x for x in self.rows_out if x[1:] != [0]*(len(x)-1)]

        # remove columns that are all zeros
        to_remove = []
        for i in range(1, len(self.rows_out[0])):
            if sum([x[i] for x in self.rows_out[1:]]) == 0:
                to_remove.append(i)

        for i in range(len(self.rows_out)):
            self.rows_out[i] = [self.rows_out[i][j] for j in range(len(self.rows_out[i])) if j not in to_remove]



    def _write_tsv(self):
        f = pyfastaq.utils.open_file_write(self.outfile)
        print('#', end='', file=f)
        for row in self.rows_out:
            print('\t'.join([str(x) for x in row]), file=f)
        pyfastaq.utils.close(f)


    def _write_js_candy_csv(self, outfile):
        f = pyfastaq.utils.open_file_write(outfile)
        # js candy needs the "name" column.
        # Names must match those used in the tree file
        print('name', *self.rows_out[0][1:], sep=',', file=f)
        for row in self.rows_out[1:]:
            print(*row, sep=',', file=f)
        pyfastaq.utils.close(f)


    def _write_xls(self):
        workbook = openpyxl.Workbook()
        worksheet = workbook.worksheets[0]
        worksheet.title = 'ARIBA_summary'
        for row in self.rows_out:
            worksheet.append(row)
        workbook.save(self.outfile)


    @staticmethod
    def _distance_score_between_values(value1, value2):
        if value1 != value2 and 0 in [value1, value2]:
            return 1
        else:
            return 0


    @classmethod
    def _distance_score_between_lists(cls, scores1, scores2):
        assert len(scores1) == len(scores2)
        return sum([cls._distance_score_between_values(scores1[i], scores2[i]) for i in range(1, len(scores1))])


    def _write_distance_matrix(self, outfile):
        if len(self.rows_out) < 3:
            raise Error('Cannot calculate distance matrix to make tree for js_candy.\n' +
                        'Only one sample present.')

        if len(self.rows_out[0]) < 2:
            raise Error('Cannot calculate distance matrix to make tree for js_candy.\n' +
                        'No genes present in output')

        with open(outfile, 'w') as f:
            sample_names = [x[0] for x in self.rows_out]
            print(*sample_names[1:], sep='\t', file=f)

            for i in range(1,len(self.rows_out)):
                scores = []
                for j in range(2, len(self.rows_out)):
                    scores.append(self._distance_score_between_lists(self.rows_out[i], self.rows_out[j]))
                print(self.rows_out[i][0], *scores, sep='\t', file=f)


    @staticmethod
    def _newick_from_dist_matrix(distance_file, outfile):
        r_script = outfile + '.tmp.R'

        with open(r_script, 'w') as f:
            print('library(ape)', file=f)
            print('a=read.table("', distance_file, '", header=TRUE, row.names=1)', sep='', file=f)
            print('h=hclust(dist(a))', file=f)
            print('write.tree(as.phylo(h), file="', outfile, '")', sep='', file=f)

        common.syscall('R CMD BATCH --no-save ' + r_script)
        os.unlink(r_script + 'out')
        os.unlink(r_script)


    def run(self):
        self._check_files_exist()
        self._gather_output_rows()
        self._filter_output_rows()
        if self.outfile.endswith('.xls'):
            self._write_xls()
        else:
            self._write_tsv()

        if self.js_candy_prefix is not None:
            self._write_js_candy_files()
