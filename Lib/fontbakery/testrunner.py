# -*- coding: <encoding name> -*-
from __future__ import absolute_import, print_function, unicode_literals

import types
from collections import OrderedDict
from itertools import chain

class Status(object):
  """ If you create a custom Status symbol, please use reverse domain
  name notation as a prefix of `name`.
  This is because all statuses are registered globally and that would
  cause name collisions otherwise.

  However, it's an intended use case for your tests to be able to yield
  custom statuses. Interpreters of the test protocol will have to skip
  statuses unknown to them or treat them in an otherwise non-fatal fashion.
  """
  def __new__(cls, name):
    """ Don't create two instances with same name.

    >>> a = Status('PASS')
    >>> a
    <Status hello>
    >>> b = Status('PASS')
    >>> b
    <Status hello>
    >>> b is a
    True
    >>> b == a
    True
    """
    instance = cls.__instances.get(name, None)
    if instance is None:
      instance = cls.__instances[name] = super(Status, cls).__new__(cls)
      setattr(instance, '_Status__name', name)
    return instance

  __instances = {}

  def __str__(self):
    return '<Status {0}>'.format(self.__name)

  __repr__ = __str__

# Status messages of the test runner protocoll



# always allowed:
INFO = Status('INFO')
WARN = Status('WARN')

# exeptional, something a programmer must fix
ERROR = Status('ERROR')

STARTSECTION = Status('STARTSECTION')
# only between STARTSECTION and ENDSECTION
STARTTEST = Status('STARTTEST')
# only between STARTTEST and ENDTEST
SKIP = Status('SKIP')
PASS = Status('PASS')
FAIL = Status('FAIL')
# ends the last test started by STARTTEST
ENDTEST = Status('ENDTEST')
# ends the last section started by STARTSECTION
ENDSECTION = Status('ENDSECTION')


class FontBakeryRunnerError(Exception):
  pass

class APIViolationError(FontBakeryRunnerError):
  def __init__(self, message, result, *args):
    self.message = message
    self.result = result
    super(APIViolationError, self).__init__(message, result, *args)

class FailedConditionError(FontBakeryRunnerError):
  """ This is a serious problem with the test suite spec and it must
  be solved.
  """
  def __init__(self, condition, error, *args):
    message = 'The condtion {0} had an error: {1} {2}'.format(condition, type(error), error)
    self.condition = condition
    self.error = error
    super(FailedConditionError, self).__init__(message, *args)

class FailedDependenciesError(FontBakeryRunnerError):
  def __init__(self, condition, error, *args):
    message = 'The condtion {0} had an error: {1} {2}'.format(condition, type(error), error)
    self.condition = condition
    self.error = error
    super(FailedDependenciesError, self).__init__(message, *args)

class MissingValueError(FontBakeryRunnerError):
  pass

class TestRunner(object):
  def __init__(self, spec, values):
    # TODO: transform all iterables that are list like to tuples
    # to make sure that they won't change anymore.
    # Also remove duplicates from list like iterables
    self._iterargs = OrderedDict()
    for singular, plural in spec.iterargs.items():
      values[plural] = tuple(values[plural])
      self._iterargs[singular] = len(values[plural])

    self._spec = spec;
    # spec.validate(values)?
    self._values = values;

    self._cache = {
      'conditions': {}
    }

  def _check_result(self, result):
    """ Check that the test returned appropriate results:
       * a tuple (<Status>, message)
       * if message is an Exception `status` must not be PASS
       Returns a Tuple which replaces each failing result with a
       failure message: (<Status FAIL>,<APIViolationError>)

       Tests will be implemented by other parties. This is to
       help implementors creating good tests, to spot erroneous
       implementations early and to make it easier to handle
       the results tuple.
    """
    if not isinstance(result, tuple):
      return (FAIL, APIViolationError(
        'Result must be a tuple but '
        'it is {0}.'.format(type(result)), result))

    if len(result) != 2:
      return (FAIL, APIViolationError(
        'Result must have 2 items, but it '
        'has {0}.'.format(len(result)), result))

    status, message = result
    # Allow booleans, but there's no way to issue a WARNING
    if isinstance(status, types.BooleanType):
      # normalize
      status = PASS if status else FAIL
      result = (status, message)

    if not isinstance(status, Status):
      return (FAIL, APIViolationError(
        'Result item `status` must be an instance of '
        'Status, but it is {0} a {1}.'.format(status, type(status)), result))

    if status == PASS and isinstance(message, Exception):
      return (FAIL, APIViolationError(
        'Result item `status` cant be a {0} '
        'since `message` is an Exception'.format(PASS), result))
    # passed:
    return result

  def _exec_test_generator(self, gen):
    """ Execute a generator returned by a test callable.
       Yield each sub-result or, in case of an error, (FAIL, exception)
    """
    try:
       for sub_result in gen:
        # Collect as much as possible
        # list(gen) would in case only produce one
        # error entry. This loop however keeps
        # all sub_results upon the point of error
        # or ends the generator.
        yield sub_result
    except Exception as e:
      yield (FAIL, e)

  def _exec_test(self, test, args):
    """ Yields test sub results.

    `test` must be a callable

    Each test result is a tuple of: (<Status>, mixed message)
    `status`: must be an instance of Status.
          If one of the `status` entries in one of the results
          is FAIL, the whole test is considered failed.
          WARN is most likely a PASS in a non strict mode and a
          FAIL in a strict mode.
    `message`:
      * If it is an `Exception` type we expect `status`
        not to be PASS
      * If it is a `string` it's a description of what passed
        or failed.
      * we'll think of an AdvancedMessageType as well, so that
        we can connect the test result with more in depth
        knowledge from the test definition.
    """
    try:
      result = test(**args)
    except Exception as e:
      result = (FAIL, e)

    # We allow the `test` callable to "yield" multiple
    # times, instead of returning just once. That's
    # a common thing for unit tests (testing multiple conditions
    # in one method) and a nice feature via yield. It will also
    # help us to be better compatible with our old style tests
    # or with pyunittest-like tests.
    if isinstance(result, types.GeneratorType):
      for sub_result in self._exec_test_generator(result):
        yield self._check_result(sub_result)
    else:
      yield self._check_result(result)

  def _evaluate_condition(self, name, iterargs, path=None):
    if path is None:
      # top level call
      path = []
    if name in path:
      raise CircularDependencyError('Condition "{0}" is a circular dependency in {1}'\
                                  .format(condition, ' -> '.join(path)))
    path.append(name)
    condition = self._spec.conditions[name]
    args = self._get_args(condition, iterargs, path)
    path.pop()
    try:
      return None, condition(**args)
    except Exception as error:
      return error, None

  def _get_condition(self, name, iterargs, path=None):
    # conditions are evaluated lazily
    key = (name, tuple(iterargs))
    if key not in self._cache['conditions']:
      err, val = self._evaluate_condition(name, iterargs, path)
      self._cache['conditions'][key] = err, val
    else:
      err, val = self._cache['conditions'][key]
    return err, val

  def _get_args(self, item, iterargs, path=None):
    # iterargs can't be optional arguments yet, we wouldn't generate
    # an execution with an empty list. I don't know if that would be even
    # feasible, so I don't add this complication for the sake of clarity.
    # If this is needed for anything useful, we'll have to figure this out.
    args = {}
    iterargsDict = dict(iterargs)
    for name in item.args:
      if name in args:
        continue;

      if name in self._spec.iterargs:
        plural = self._spec.iterargs[name]
        index = iterargsDict[name]
        args[name] = self._values[plural][index]
      elif name in self._spec.conditions:
        error, args[name] = self._get_condition(name, iterargs, path)
        if error:
          raise error
      elif name in self._values:
        args[name] = self._values[name]
      elif name not in item.optionalArgs:
        raise MissingValueError('Value "{0}" is undefined.'.format(name))
    return args;

  def _is_negated(self, name):
    stripped = name.strip()
    if stripped.startswith('not '):
      return True, stripped[4:].strip()
    if stripped.startswith('!'):
      return True, stripped[1:].strip()
    return False, stripped

  def _get_test_dependencies(self, test, iterargs):
    failed_conditions = False
    unfulfilled_conditions = []
    for condition in test.conditions:
      negate, name = self._is_negated(condition)
      err, val = self._get_condition(name, iterargs)
      if negate:
        val = not val
      if err:
        failed_conditions = True
        status = (ERROR, FailedConditionError(condition, err))
        yield (status, None)
        continue
      if not val:
        unfulfilled_conditions.append(condition)
    if failed_conditions:
      return

    if unfulfilled_conditions:
      # This will make the test neither pass nor fail
      status = (SKIP, 'Unfulfilled Conditions: {}'.format(
                                    ', '.join(unfulfilled_conditions)))
      yield (status, None)
      return

    try:
      yield None, self._get_args(test, iterargs)
    except Exception as error:
      status = (ERROR, FailedDependenciesError(condition, err))
      yield (status, None)

  def _run_test(self, test, iterargs):
    # A test is more than just a function, it carries
    # a lot of meta-data for us, in this case we can use
    # meta-data to learn how to call the test (via
    # configuration or inspection, where inspection would be
    # the default and configuration could be used to override
    # inspection results).
    for skipped, args in self._get_test_dependencies(test, iterargs):
      # FIXME: test is not a message
      # so, to us it as a message, it should have a "message-interface"
      # TODO: describe generic "message-interface"
      yield STARTTEST, test
      if skipped is not None:
        # `skipped` is a normal result tuple (status, message)
        # where `status` is either FAIL for unmet dependencies
        # or SKIP for unmet conditions or ERROR. A status of SKIP is
        # never a failed test.
        # ERROR is either a missing dependency or a condition that raised
        # an exception. This shouldn't happen when everyting is set up
        # correctly.
        yield skipped
      else:
        for sub_result in self._exec_test(test, args):
          yield sub_result
        # The only reason to yield this is to make it testable
        # that a test ran to its end, or, if we start to allow
        # nestable subtests. Otherwise, a STARTTEST would end the
        # previous test implicitly.
        # We can also use it to display status updates to the user.
      yield ENDTEST, None

  def run(self):
    for section in self._spec.testsections:
      yield STARTSECTION, section
      for test, iterargs in section.execution_order(self._iterargs
                             , getConditionByName=self._spec.conditions.get):
        for event in self._run_test(test, iterargs):
          yield event;
      yield ENDSECTION, None

class Section(object):
  def __init__(self, name, tests, order=None, description=None):
    self.name = name;
    self.description = description;
    self._tests = tests;
    # a list of iterarg-names
    self._order = order or [];

  def __repr__(self):
    return '<Section: {0}>'.format(self.name)

  def _get_aggregate_args(self, test, key, getConditionByName):
    dependencies = getattr(test, key) + test.conditions[:]
    args = set()
    while dependencies:
      name = dependencies.pop()
      if name in args:
        continue
      args.add(name)
      # if this is a condition, expand its dependencies
      c = getConditionByName(name, None)
      if c is None:
        continue
      dependencies += [dependency for dependency in getattr(c, key)
                                              if dependency not in args]
    return args

  def _analyze_tests(self, all_args, getConditionByName):
    args = list(all_args)
    args.reverse()
    scopes = [(test, tuple(), tuple()) for test in self._tests]
    aggregatedArgs = {
      'args': {test.name:self._get_aggregate_args(
                                test, 'args', getConditionByName)
                              for test in self._tests }
    , 'mandatoryArgs': {test.name: self._get_aggregate_args(
                                test, 'mandatoryArgs', getConditionByName)
                              for test in self._tests }
    }
    saturated = []
    while args:
      new_scopes = []
      # args_set must contain all current args, hence it's before the pop
      args_set = set(args)
      arg = args.pop()
      for test, signature, scope in scopes:
        if not len(aggregatedArgs['args'][test.name] & args_set):
          # there's no args no more or no arguments of test are
          # in args
          target = saturated
        elif arg == '*test' or arg in aggregatedArgs['mandatoryArgs'][test.name]:
          signature += (1, )
          scope += (arg, )
          target = new_scopes
        else:
          # there's still a tail of args and test requires one of the
          # args in tail but not the current arg
          signature += (0, )
          target = new_scopes
        target.append((test, signature, scope))
      scopes = new_scopes
    return saturated + scopes;

  def _make_generator(self, iterargs, k):
    for item in range(iterargs[k]):
      yield item

  def _execute_section(self, iterargs, section, items):
    if section is None:
      # base case: terminate recursion
      for test, signature, scope in items:
        yield test, []
    elif not section[0]:
      # no sectioning on this level
      for item in self._execute_scopes(iterargs, items):
        yield item
    elif section[1] == '*test':
      # enforce sectioning by test
      for section_item in items:
        for item in self._execute_scopes(iterargs, [section_item]):
          yield item
    else:
      # section by gen_arg, i.e. ammend with changing arg.
      _, gen_arg = section
      for index in range(iterargs[gen_arg]):
        for test, args in self._execute_scopes(iterargs, items):
          yield test, [(gen_arg, index)] + args

  def _execute_scopes(self, iterargs, scopes):
    generators = []
    items = []
    current_section = None
    last_section = None
    seen = set()
    for test, signature, scope in scopes:
      if len(signature):
        # items are left
        if signature[0]:
          gen_arg = scope[0]
          scope = scope[1:]
          current_section = True, gen_arg
        else:
          current_section = False, None
        signature = signature[1:]
      else:
        current_section = None

      assert current_section not in seen, 'Scopes are badly sorted.{0} in {1}'.format(current_section, seen)

      if current_section != last_section:
        if len(items):
          # flush items
          generators.append(self._execute_section(iterargs, last_section, items))
          items = []
          seen.add(last_section)
        last_section = current_section
      items.append((test, signature, scope))
    # clean up left overs
    if len(items):
      generators.append(self._execute_section(iterargs, current_section, items))

    for item in chain(*generators):
      yield item

  def execution_order(self, iterargs, getConditionByName, reverse=False):
    """
      order must:
        a) contain all variable args (we're appending missing ones)
        b) not contian duplictates (we're removing repeated items)

      order may contain *iterargs otherwise it is appended
      to the end

      order may contain "*test" otherwise, it is like *test is appended
      to the end (Not done explicitly though).
    """
    stack = self._order[:]
    if '*iterargs' not in stack:
      stack.append('*iterargs')
    stack.reverse()

    full_order = []
    seen = set()
    while len(stack):
      item = stack.pop()
      if item in seen:
        continue
      seen.add(item)
      if item == '*iterargs':
        all_iterargs = list(iterargs.keys())
        # assuming there is a meaningful order
        all_iterargs.reverse()
        stack += all_iterargs
        continue
      full_order.append(item)

    scopes = self._analyze_tests(full_order, getConditionByName=getConditionByName)
    key = lambda (test, signature, scope): signature
    scopes.sort(key=key, reverse=reverse)

    for test, args in self._execute_scopes(iterargs, scopes):
      yield test, args


class Spec(object):
  def __init__(self, testsections, iterargs, conditions=None):
    '''
      testsections: a list of sections, which are ideally ordered sets of
          individual tests.
          It makes no sense to have tests repeatedly, they yield the same
          results anyway.
          FIXME: Should we detect this and inform the user then skip the repeated tests.
      iterargs: maping 'singular' variable names to the iterable in values
          e.g.: `{'font': 'fonts'}` in this case fonts must be iterable AND
          'font' may not be a value NOR a condition name.

    We will:
      a) get all needed values/variable names from here
      b) add some validation, so that we know the values match
         our expectations! These values must be treated asuser input!
    '''
    self.testsections = testsections
    self.iterargs = iterargs
    self.conditions = conditions or {}

if __name__ == '__main__':

  from test import condition, test

  conditions={}
  def registerCondition(condition):
    conditions[condition.name] = condition
  tests=[]
  registerTest = tests.append

  @condition
  def fontNameNumber(font):
    return int(font.split('_')[1])
  registerCondition(fontNameNumber)

  @condition
  def isOddFontName(fontNameNumber):
    return  fontNameNumber % 2 == 1
  registerCondition(isOddFontName)


  @test(
      id='com.google.fonts/1'
    , conditions=['isOddFontName']
    , description='Is the odd fontname bigger than one?'
  )
  def oddNameBiggerThanOne(fontNameNumber):
    return PASS if fontNameNumber > 1 else FAIL, fontNameNumber
  registerTest(oddNameBiggerThanOne)


  @test(
      id='com.google.fonts/2'
    , conditions=['not isOddFontName']
    , description='Is the even fontname bigger than two?'
  )
  def evenNameBiggerThanTwo(fontNameNumber):
    return PASS if fontNameNumber > 2 else FAIL, fontNameNumber
  registerTest(evenNameBiggerThanTwo)

  testsections=[Section('Default', tests)]

  googleSpec = Spec(
      conditions=conditions
    , testsections=testsections
    , iterargs={'font': 'fonts'}
  )
  fonts = ['font_1', 'font_2', 'font_3', 'font_4']
  runner = TestRunner(googleSpec, {'fonts': fonts})
  for event, message in runner.run():
    if event == ERROR:
      print(event, type(message).__name__, '>>>', message)
    else:
      print('{} >>> {}'.format(event, message))

