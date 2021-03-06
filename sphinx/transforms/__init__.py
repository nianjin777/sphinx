# -*- coding: utf-8 -*-
"""
    sphinx.transforms
    ~~~~~~~~~~~~~~~~~

    Docutils transforms used by Sphinx when reading documents.

    :copyright: Copyright 2007-2017 by the Sphinx team, see AUTHORS.
    :license: BSD, see LICENSE for details.
"""

from docutils import nodes
from docutils.transforms import Transform, Transformer
from docutils.transforms.parts import ContentsFilter
from docutils.utils import new_document

from sphinx import addnodes
from sphinx.locale import _
from sphinx.util import logging
from sphinx.util.i18n import format_date
from sphinx.util.nodes import apply_source_workaround

if False:
    # For type annotation
    from sphinx.application import Sphinx  # NOQA
    from sphinx.config import Config  # NOQA
    from sphinx.domain.std import StandardDomain  # NOQA
    from sphinx.environment import BuildEnvironment  # NOQA


logger = logging.getLogger(__name__)

default_substitutions = set([
    'version',
    'release',
    'today',
])


class SphinxTransform(Transform):
    """
    A base class of Transforms.

    Compared with ``docutils.transforms.Transform``, this class improves accessibility to
    Sphinx APIs.

    The subclasses can access following objects and functions:

    self.app
        The application object (:class:`sphinx.application.Sphinx`)
    self.config
        The config object (:class:`sphinx.config.Config`)
    self.env
        The environment object (:class:`sphinx.environment.BuildEnvironment`)
    """

    @property
    def app(self):
        # type: () -> Sphinx
        return self.document.settings.env.app

    @property
    def env(self):
        # type: () -> BuildEnvironment
        return self.document.settings.env

    @property
    def config(self):
        # type: () -> Config
        return self.document.settings.env.config


class SphinxTransformer(Transformer):
    """
    A transformer for Sphinx.
    """

    document = None  # type: nodes.Node
    env = None  # type: BuildEnvironment

    def set_environment(self, env):
        # type: (BuildEnvironment) -> None
        self.env = env

    def apply_transforms(self):
        # type: () -> None
        if isinstance(self.document, nodes.document):
            Transformer.apply_transforms(self)
        else:
            # wrap the target node by document node during transforming
            try:
                document = new_document('')
                if self.env:
                    document.settings.env = self.env
                document += self.document
                self.document = document
                Transformer.apply_transforms(self)
            finally:
                self.document = self.document[0]


class DefaultSubstitutions(SphinxTransform):
    """
    Replace some substitutions if they aren't defined in the document.
    """
    # run before the default Substitutions
    default_priority = 210

    def apply(self):
        # type: () -> None
        # only handle those not otherwise defined in the document
        to_handle = default_substitutions - set(self.document.substitution_defs)
        for ref in self.document.traverse(nodes.substitution_reference):
            refname = ref['refname']
            if refname in to_handle:
                text = self.config[refname]
                if refname == 'today' and not text:
                    # special handling: can also specify a strftime format
                    text = format_date(self.config.today_fmt or _('%b %d, %Y'),
                                       language=self.config.language)
                ref.replace_self(nodes.Text(text, text))


class MoveModuleTargets(SphinxTransform):
    """
    Move module targets that are the first thing in a section to the section
    title.

    XXX Python specific
    """
    default_priority = 210

    def apply(self):
        # type: () -> None
        for node in self.document.traverse(nodes.target):
            if not node['ids']:
                continue
            if ('ismod' in node and
                    node.parent.__class__ is nodes.section and
                    # index 0 is the section title node
                    node.parent.index(node) == 1):
                node.parent['ids'][0:0] = node['ids']
                node.parent.remove(node)


class HandleCodeBlocks(SphinxTransform):
    """
    Several code block related transformations.
    """
    default_priority = 210

    def apply(self):
        # type: () -> None
        # move doctest blocks out of blockquotes
        for node in self.document.traverse(nodes.block_quote):
            if all(isinstance(child, nodes.doctest_block) for child
                   in node.children):
                node.replace_self(node.children)
        # combine successive doctest blocks
        # for node in self.document.traverse(nodes.doctest_block):
        #    if node not in node.parent.children:
        #        continue
        #    parindex = node.parent.index(node)
        #    while len(node.parent) > parindex+1 and \
        #            isinstance(node.parent[parindex+1], nodes.doctest_block):
        #        node[0] = nodes.Text(node[0] + '\n\n' +
        #                             node.parent[parindex+1][0])
        #        del node.parent[parindex+1]


class AutoNumbering(SphinxTransform):
    """
    Register IDs of tables, figures and literal_blocks to assign numbers.
    """
    default_priority = 210

    def apply(self):
        # type: () -> None
        domain = self.env.get_domain('std')  # type: StandardDomain

        for node in self.document.traverse(nodes.Element):
            if domain.is_enumerable_node(node) and domain.get_numfig_title(node) is not None:
                self.document.note_implicit_target(node)


class SortIds(SphinxTransform):
    """
    Sort secion IDs so that the "id[0-9]+" one comes last.
    """
    default_priority = 261

    def apply(self):
        # type: () -> None
        for node in self.document.traverse(nodes.section):
            if len(node['ids']) > 1 and node['ids'][0].startswith('id'):
                node['ids'] = node['ids'][1:] + [node['ids'][0]]


class CitationReferences(SphinxTransform):
    """
    Replace citation references by pending_xref nodes before the default
    docutils transform tries to resolve them.
    """
    default_priority = 619

    def apply(self):
        # type: () -> None
        for citnode in self.document.traverse(nodes.citation_reference):
            cittext = citnode.astext()
            refnode = addnodes.pending_xref(cittext, refdomain='std', reftype='citation',
                                            reftarget=cittext, refwarn=True,
                                            ids=citnode["ids"])
            refnode.source = citnode.source or citnode.parent.source
            refnode.line = citnode.line or citnode.parent.line
            refnode += nodes.Text('[' + cittext + ']')
            citnode.parent.replace(citnode, refnode)


TRANSLATABLE_NODES = {
    'literal-block': nodes.literal_block,
    'doctest-block': nodes.doctest_block,
    'raw': nodes.raw,
    'index': addnodes.index,
    'image': nodes.image,
}


class ApplySourceWorkaround(SphinxTransform):
    """
    update source and rawsource attributes
    """
    default_priority = 10

    def apply(self):
        # type: () -> None
        for n in self.document.traverse():
            if isinstance(n, (nodes.TextElement, nodes.image)):
                apply_source_workaround(n)


class AutoIndexUpgrader(SphinxTransform):
    """
    Detect old style; 4 column based indices and automatically upgrade to new style.
    """
    default_priority = 210

    def apply(self):
        # type: () -> None
        for node in self.document.traverse(addnodes.index):
            if 'entries' in node and any(len(entry) == 4 for entry in node['entries']):
                msg = ('4 column based index found. '
                       'It might be a bug of extensions you use: %r' % node['entries'])
                logger.warning(msg, location=node)
                for i, entry in enumerate(node['entries']):
                    if len(entry) == 4:
                        node['entries'][i] = entry + (None,)


class ExtraTranslatableNodes(SphinxTransform):
    """
    make nodes translatable
    """
    default_priority = 10

    def apply(self):
        # type: () -> None
        targets = self.config.gettext_additional_targets
        target_nodes = [v for k, v in TRANSLATABLE_NODES.items() if k in targets]
        if not target_nodes:
            return

        def is_translatable_node(node):
            # type: (nodes.Node) -> bool
            return isinstance(node, tuple(target_nodes))

        for node in self.document.traverse(is_translatable_node):
            node['translatable'] = True


class FilterSystemMessages(SphinxTransform):
    """Filter system messages from a doctree."""
    default_priority = 999

    def apply(self):
        # type: () -> None
        filterlevel = self.config.keep_warnings and 2 or 5
        for node in self.document.traverse(nodes.system_message):
            if node['level'] < filterlevel:
                logger.debug('%s [filtered system message]', node.astext())
                node.parent.remove(node)


class SphinxContentsFilter(ContentsFilter):
    """
    Used with BuildEnvironment.add_toc_from() to discard cross-file links
    within table-of-contents link nodes.
    """
    def visit_pending_xref(self, node):
        # type: (nodes.Node) -> None
        text = node.astext()
        self.parent.append(nodes.literal(text, text))
        raise nodes.SkipNode

    def visit_image(self, node):
        # type: (nodes.Node) -> None
        raise nodes.SkipNode
