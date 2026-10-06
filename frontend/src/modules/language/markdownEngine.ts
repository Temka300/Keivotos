import {EditorState} from '@codemirror/state';
import {markdown} from '@codemirror/lang-markdown';
import {syntaxTree} from '@codemirror/language';
import {minimalSetup} from 'codemirror';
import {Decoration,EditorView,ViewPlugin,keymap,type DecorationSet,type ViewUpdate} from '@codemirror/view';

export type Format='heading-1'|'heading-2'|'heading-3'|'heading-4'|'heading-5'|'heading-6'|'rule'|'bold'|'italic'|'bold-italic'|'highlight';
export interface MarkdownEngine{format:(kind:Format)=>void;destroy:()=>void;}

function isLiteral(state:EditorState,position:number){
  let node:ReturnType<ReturnType<typeof syntaxTree>['resolveInner']>|null=syntaxTree(state).resolveInner(position,1);
  while(node){
    if(['InlineCode','FencedCode','CodeBlock','HTMLBlock'].includes(node.name))return true;
    node=node.parent;
  }
  return false;
}
function escaped(line:string,index:number){
  let slashes=0;
  for(let at=index-1;at>=0&&line[at]==='\\';at--)slashes++;
  return slashes%2===1;
}
function highlights(editor:EditorView):DecorationSet{
  const marks=[];
  for(const range of editor.visibleRanges){
    let line=editor.state.doc.lineAt(range.from);
    while(line.from<=range.to){
      const pattern=/==([^=\n]|=(?!=))+==/g;
      for(const match of line.text.matchAll(pattern)){
        const start=match.index??0;
        if(escaped(line.text,start)||isLiteral(editor.state,line.from+start))continue;
        const from=line.from+start+2,to=line.from+start+match[0].length-2;
        if(from<to)marks.push(Decoration.mark({class:'cm-markdown-highlight'}).range(from,to));
      }
      if(line.to===editor.state.doc.length)break;
      line=editor.state.doc.line(line.number+1);
    }
  }
  return Decoration.set(marks,true);
}
const highlightPlugin=ViewPlugin.fromClass(class{
  decorations:DecorationSet;
  constructor(editor:EditorView){this.decorations=highlights(editor);}
  update(update:ViewUpdate){if(update.docChanged||update.viewportChanged)this.decorations=highlights(update.view);}
},{decorations:plugin=>plugin.decorations});

export function mountMarkdownEditor(host:HTMLDivElement,value:string,label:string,onChange:(text:string)=>void):MarkdownEngine{
  let view:EditorView;
  function surround(mark:string){
    const selection=view.state.selection.main;
    const selected=view.state.doc.sliceString(selection.from,selection.to);
    view.dispatch({
      changes:{from:selection.from,to:selection.to,insert:mark+selected+mark},
      selection:{anchor:selection.from+mark.length,head:selection.to+mark.length},
    });
    view.focus();
  }
  function format(kind:Format){
    if(kind.startsWith('heading-')){
      const count=Number(kind.slice(-1));
      const line=view.state.doc.lineAt(view.state.selection.main.from);
      const prefix=/^#{1,6}[ \t]+/.exec(line.text);
      view.dispatch({changes:{from:line.from,to:line.from+(prefix?.[0].length??0),insert:'#'.repeat(count)+' '}});
      view.focus();
    }else if(kind==='rule'){
      const selection=view.state.selection.main;
      const before=view.state.doc.sliceString(0,selection.from);
      const after=view.state.doc.sliceString(selection.to);
      const left=!before||before.endsWith('\n\n')?'':before.endsWith('\n')?'\n':'\n\n';
      const right=!after?'\n':after.startsWith('\n\n')?'':after.startsWith('\n')?'\n':'\n\n';
      const insert=left+'---'+right;
      view.dispatch({changes:{from:selection.from,to:selection.to,insert},selection:{anchor:selection.from+insert.length}});
      view.focus();
    }else surround(kind==='bold'?'**':kind==='italic'?'*':kind==='bold-italic'?'***':'==');
  }
  view=new EditorView({parent:host,state:EditorState.create({doc:value,extensions:[
    minimalSetup,
    markdown({completeHTMLTags:false,pasteURLAsLink:false}),
    EditorView.lineWrapping,
    EditorView.contentAttributes.of({'aria-label':label}),
    keymap.of([
      {key:'Mod-b',run:()=>{format('bold');return true;}},
      {key:'Mod-i',run:()=>{format('italic');return true;}},
    ]),
    highlightPlugin,
    EditorView.updateListener.of(update=>{if(update.docChanged)onChange(update.state.doc.toString());}),
    EditorView.theme({
      '&':{height:'100%',backgroundColor:'#101016',color:'#eee'},
      '.cm-scroller':{overflow:'auto',fontFamily:'ui-monospace,SFMono-Regular,Consolas,monospace'},
      '.cm-content':{minHeight:'100%',padding:'24px',fontSize:'15px',lineHeight:'1.65',caretColor:'#eee'},
      '.cm-gutters':{backgroundColor:'#17171f',color:'#777787',borderRight:'1px solid #292936'},
      '.cm-cursor':{borderLeftColor:'#eee'},
      '.cm-selectionBackground':{backgroundColor:'#51406e !important'},
      '.cm-markdown-highlight':{backgroundColor:'#8e6a2d88',borderRadius:'2px'},
      '&.cm-focused':{outline:'2px solid var(--accent)',outlineOffset:'-2px'},
    }),
  ]})});
  return {format,destroy:()=>view.destroy()};
}
