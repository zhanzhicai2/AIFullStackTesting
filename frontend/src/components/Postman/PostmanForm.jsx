import React from 'react';
import {Card,} from 'antd';
import {connect} from '@umijs/max';
import PostmanBody from "@/components/Postman/PostmanBody";

const PostmanForm = (props) => {
  return (
    <Card variant={props.bordered ? 'borderless' : 'outlined'}>
      <PostmanBody {...props}/>
    </Card>
  );
};

export default connect(({gconfig}) => ({gconfig}))(PostmanForm);
